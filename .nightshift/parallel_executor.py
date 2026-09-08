#!/usr/bin/env python3
"""
Parallel Execution Primitives for Nightshift Kit.

Provides planning, fan-out, fan-in, and worktree lifecycle management
for parallel spec execution with git worktree-based isolation.
"""

import enum
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import uuid
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import yaml

from status_store import (
    StatusStore,
    StatusStoreError,
    is_canonical_repository_relative_path,
)

from dependency_registry import (
    DependencyRegistryResolver,
    parse_requires_specs,
    parse_requires_specs_text,
)

from worktree_paths import (
    WorktreePathError,
    assert_managed_worktree_path,
    assert_worktree_owner,
    worktree_path,
)


GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ParallelLayer:
    """A group of specs that can execute concurrently."""

    layer_index: int
    spec_ids: List[str]  # sorted alphabetically
    is_parallel: bool  # True if len(spec_ids) > 1
    dependencies_satisfied_by: List[int]  # indices of preceding layers

    def __len__(self) -> int:
        return len(self.spec_ids)


class ExecutionStrategy(enum.Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL_LAYERS = "PARALLEL_LAYERS"


@dataclass(frozen=True)
class AdmissionSpec:
    """The minimal, immutable state needed to make an admission decision."""

    spec_id: str
    status: str
    after: Tuple[str, ...] = ()
    touches: Tuple[str, ...] = ()
    priority: int = 1
    spec_path: Optional[Path] = None


@dataclass
class AdmissionDecision:
    """One deterministic admission outcome, including a human-readable reason."""

    spec_id: str
    disposition: str  # admitted/runnable/deferred/blocked/invalid/not_ready
    reason: str
    detail: str
    blocking_ancestor: Optional[str] = None
    conflicting_spec_ids: List[str] = field(default_factory=list)
    conflicting_surfaces: List[str] = field(default_factory=list)


@dataclass
class AdmissionPlan:
    """A serializable snapshot of a dynamic ready-frontier decision."""

    worker_limit: int
    active_spec_ids: List[str]
    missing_touches_policy: str
    frontier: List[str]
    admitted: List[str]
    decisions: List[AdmissionDecision]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_human_readable(self) -> str:
        """Render a compact review artifact without changing planner state."""
        lines = [
            "# Parallel Admission Plan",
            "",
            f"- Worker limit: {self.worker_limit}",
            f"- Active workers: {', '.join(self.active_spec_ids) or 'none'}",
            f"- Missing/coarse touches policy: {self.missing_touches_policy}",
            f"- Ready frontier: {', '.join(self.frontier) or 'none'}",
            f"- Admitted: {', '.join(self.admitted) or 'none'}",
            "",
            "## Decisions",
            "",
        ]
        for decision in self.decisions:
            detail = f" — {decision.detail}" if decision.detail else ""
            lines.append(
                f"- `{decision.spec_id}`: **{decision.disposition}** "
                f"(`{decision.reason}`){detail}"
            )
        return "\n".join(lines) + "\n"


@dataclass
class WorktreeHandle:
    """Tracks a single spec's worktree throughout its lifecycle."""

    spec_id: str
    worktree_path: Path
    branch_name: str
    events_dir: Path
    checkpoint_dir: Path
    status: str = "pending"  # pending/running/completed/failed/conflict
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    outcome: Optional[dict] = None
    files_changed: List[str] = field(default_factory=list)
    declared_touches: List[str] = field(default_factory=list)
    # Release surfaces (CHANGELOG/version/handoff) are applied by the parent
    # only.  A worker may describe a requested edit here but must not commit it.
    release_intents: List[Dict[str, Any]] = field(default_factory=list)
    integrity_receipt_path: Optional[str] = None
    integrity_receipt_sha256: Optional[str] = None
    integrity_run_id: Optional[str] = None
    # Coordinator-issued logical run identity for the immutable terminal
    # decision.  This is intentionally separate from lifecycle projection.
    terminal_run_id: Optional[str] = None
    canonical_spec_path: Optional[Path] = None
    integrity_acceptance: Optional[Dict[str, Any]] = None
    # Full LOOP completion evidence is decided by the coordinator before this
    # handle may enter integration.  It is distinct from payload integrity.
    completion_evidence_acceptance: Optional[Dict[str, Any]] = None
    # Parent-private immutable object accepted by independent verification.
    # When present, the serialized queue must apply this object rather than the
    # mutable branch ref and must refuse any branch-tip drift.
    verified_revision: Optional[str] = None


@dataclass
class DispatchedWorker:
    """Coordinator-owned record for one single-spec concurrent worker."""

    spec_id: str
    run_id: str
    handle: WorktreeHandle
    worker: object


def parallel_worker_limit(config: dict) -> Optional[int]:
    """Return an opt-in worker limit, or ``None`` for fail-closed sequential mode."""
    settings = config.get("parallel_admission")
    if not isinstance(settings, dict):
        return None
    limit = settings.get("worker_limit", 1)
    # One worker is intentionally sequential; malformed input must never enable
    # concurrent execution by accident.
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 2:
        return None
    return limit


class BoundedWorktreeDispatcher:
    """Refill a live admission frontier with isolated, one-spec workers.

    The class deliberately knows nothing about a particular agent harness.  The
    injected ``start_worker`` and ``poll_worker`` hooks make lifecycle behaviour
    deterministic in unit tests and keep the coordinator as the sole scheduler.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        project_root: Path,
        specs_dir: Path,
        config: dict,
        status_store: object,
        start_worker,
        poll_worker,
        janitor=None,
        prepare=None,
        admit_worker=None,
        terminal_gate=None,
        dispatch_guard=None,
        selected_spec_ids: Optional[Iterable[str]] = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.project_root = Path(project_root)
        self.specs_dir = Path(specs_dir)
        self.config = config
        self.status_store = status_store
        self.start_worker = start_worker
        self.poll_worker = poll_worker
        self.janitor = janitor
        self.prepare = prepare
        self.admit_worker = admit_worker
        self.terminal_gate = terminal_gate
        self.dispatch_guard = dispatch_guard
        self.selected_spec_ids = (
            frozenset(str(spec_id) for spec_id in selected_spec_ids)
            if selected_spec_ids is not None else None
        )
        self.run_id = uuid.uuid4().hex
        self.active: Dict[str, DispatchedWorker] = {}
        self._completed: List[WorktreeHandle] = []
        self._failed: List[Dict[str, Any]] = []
        self._dependency_resolver = DependencyRegistryResolver(self.specs_dir)
        self._dependency_statuses: Dict[str, str] = {}
        self._dependency_errors: Dict[str, str] = {}
        self._dependency_details: Dict[str, str] = {}
        self.last_plan: AdmissionPlan | None = None

    @property
    def enabled(self) -> bool:
        settings = self.config.get("parallel_admission")
        return (
            parallel_worker_limit(self.config) is not None
            and isinstance(settings, dict)
            and settings.get("missing_touches_policy", "exclusive") in {"exclusive", "allow"}
        )

    def advance(self) -> List[DispatchedWorker]:
        """Process completions, recompute admission, and fill available slots."""
        if not self.enabled:
            return []
        self._collect_completed()
        if self.dispatch_guard is not None and not self.dispatch_guard():
            return []
        specs = self._load_specs()
        limit = parallel_worker_limit(self.config)
        assert limit is not None
        settings = self.config.get("parallel_admission") or {}
        plan = plan_dynamic_admission(
            specs,
            limit,
            active_specs=[self._admission_spec_for_active(item) for item in self.active.values()],
            missing_touches_policy=settings.get("missing_touches_policy", "exclusive"),
            dependency_statuses=self._dependency_statuses,
            dependency_errors=self._dependency_errors,
            dependency_details=self._dependency_details,
        )
        self.last_plan = plan
        launched: List[DispatchedWorker] = []
        by_id = {spec.spec_id: spec for spec in specs}
        for spec_id in plan.admitted:
            if spec_id in self.active:
                continue
            launched.append(self._launch(by_id[spec_id]))
        return launched

    def drain_completed(self) -> List[WorktreeHandle]:
        """Transfer completed worker handles to the coordinator integration owner."""
        completed, self._completed = self._completed, []
        return completed

    def drain_failed(self) -> List[Dict[str, Any]]:
        """Transfer observed worker failures to the coordinator terminal owner."""
        failed, self._failed = self._failed, []
        return failed

    def _load_specs(self) -> List[AdmissionSpec]:
        specs: List[AdmissionSpec] = []
        qualified_by_consumer: Dict[str, tuple[tuple[tuple[str, str], ...], str | None]] = {}
        for path in sorted(self.specs_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            if not content.startswith("---"):
                continue
            parts = content.split("---", 2)
            if len(parts) < 3:
                continue
            try:
                data = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                # A syntactically malformed declared field belongs to this
                # consumer's admission decision; it must not abort unrelated
                # specs. Recover only the minimal identity/status needed to
                # represent that local refusal.
                requires_specs, requires_specs_error = parse_requires_specs_text(parts[1])
                if requires_specs_error is None:
                    continue
                id_match = re.search(r"^\s*id:\s*(\S+)\s*$", parts[1], re.MULTILINE)
                if not id_match:
                    continue
                status_match = re.search(r"^\s*status:\s*(\S+)\s*$", parts[1], re.MULTILINE)
                priority_match = re.search(r"^\s*priority:\s*(\d+)\s*$", parts[1], re.MULTILINE)
                data = {
                    "id": id_match.group(1),
                    "status": status_match.group(1) if status_match else "draft",
                    "priority": int(priority_match.group(1)) if priority_match else 1,
                }
                qualified_by_consumer[id_match.group(1)] = (
                    requires_specs, requires_specs_error
                )
            spec_id = data.get("id")
            if not isinstance(spec_id, str):
                continue
            if self.selected_spec_ids is not None and spec_id not in self.selected_spec_ids:
                continue
            checkpoint = self.status_store.get_state(spec_id)
            status = (checkpoint or {}).get("status", data.get("status", "draft"))
            if spec_id not in qualified_by_consumer:
                requires_specs, requires_specs_error = parse_requires_specs(data)
                qualified_by_consumer[spec_id] = (requires_specs, requires_specs_error)
            specs.append(AdmissionSpec(
                spec_id=spec_id,
                status=status,
                after=tuple(data.get("after") or ()),
                touches=tuple(data.get("touches") or ()),
                priority=int(data.get("priority", 1)),
                spec_path=path.resolve(),
            ))
        # Admission must observe a prerequisite's current on-disk status on
        # every refill; the resolver's short structural cache is unsuitable for
        # the pending -> done transition that unlocks a live worker slot.
        self._dependency_resolver.invalidate()
        statuses: Dict[str, str] = {}
        errors: Dict[str, str] = {}
        details: Dict[str, str] = {}
        resolved_specs: List[AdmissionSpec] = []
        for spec in specs:
            requirements, parse_error = qualified_by_consumer[spec.spec_id]
            resolution = self._dependency_resolver.resolve_qualified(
                spec.spec_id, requirements, parse_error=parse_error
            )
            statuses.update(resolution.statuses)
            errors.update(resolution.errors)
            details.update(resolution.details)
            resolved_specs.append(AdmissionSpec(
                spec.spec_id,
                spec.status,
                spec.after + resolution.dependency_keys,
                spec.touches,
                spec.priority,
                spec.spec_path,
            ))
        self._dependency_statuses = statuses
        self._dependency_errors = errors
        self._dependency_details = details
        return resolved_specs

    def _admission_spec_for_active(self, worker: DispatchedWorker) -> AdmissionSpec:
        for spec in self._load_specs():
            if spec.spec_id == worker.spec_id:
                return AdmissionSpec(
                    spec.spec_id, "in_progress", spec.after, spec.touches,
                    spec.priority, spec.spec_path,
                )
        return AdmissionSpec(worker.spec_id, "in_progress")

    def _launch(self, spec: AdmissionSpec) -> DispatchedWorker:
        if self.janitor is not None:
            self.janitor()
        # The status checkpoint is deliberately written before creating the
        # worker.  A crash between these operations is visible and recoverable.
        worker_run_id = f"{self.run_id}-{spec.spec_id}"
        self.status_store.update_state(
            spec.spec_id, "in_progress", run_id=worker_run_id,
            source="coordinator", note="parallel dispatch admitted",
        )
        layer = ParallelLayer(0, [spec.spec_id], False, [])
        handle = fan_out(layer, self.repo_root, branch_prefix=f"nightshift/{self.run_id}")[0]
        handle.terminal_run_id = worker_run_id
        handle.canonical_spec_path = spec.spec_path
        handle.declared_touches = list(spec.touches)
        handle.events_dir = handle.worktree_path / ".nightshift" / "runs" / worker_run_id / spec.spec_id / "events"
        handle.checkpoint_dir = handle.worktree_path / ".nightshift" / "runs" / worker_run_id / spec.spec_id / "checkpoints"
        prepare = self.prepare or prepare_worktrees
        prepared = prepare([handle], self.repo_root)[0]
        if prepared.status == "failed":
            self.status_store.update_state(
                spec.spec_id, "pending", run_id=worker_run_id, source="coordinator",
                note="worktree preparation failed; recoverable",
            )
            raise RuntimeError(f"unable to create worktree for {spec.spec_id}")
        if self.admit_worker is not None:
            admission = self.admit_worker(spec.spec_id, prepared, worker_run_id)
            if not isinstance(admission, dict) or not admission.get("ok"):
                prepared.status = "held"
                raise RuntimeError(f"managed payload admission denied for {spec.spec_id}")
            prepared.integrity_receipt_path = admission.get("integrity_receipt_path")
            prepared.integrity_receipt_sha256 = admission.get("integrity_receipt_sha256")
            prepared.integrity_run_id = admission.get("integrity_run_id") or worker_run_id
        worker = self.start_worker(spec.spec_id, prepared, worker_run_id)
        dispatched = DispatchedWorker(spec.spec_id, worker_run_id, prepared, worker)
        self.active[spec.spec_id] = dispatched
        return dispatched

    def _collect_completed(self) -> None:
        for spec_id, dispatched in list(self.active.items()):
            outcome = self.poll_worker(dispatched.worker)
            if outcome is None:
                continue
            self.active.pop(spec_id)
            success = isinstance(outcome, dict) and outcome.get("status") == "success"
            if success and self.terminal_gate is not None:
                acceptance = self.terminal_gate(dispatched.handle, outcome)
                if not isinstance(acceptance, dict) or not acceptance.get("ok"):
                    dispatched.handle.status = "held"
                    dispatched.handle.outcome = outcome if isinstance(outcome, dict) else {"outcome": str(outcome)}
                    dispatched.handle.integrity_acceptance = acceptance if isinstance(acceptance, dict) else {"outcome": "indeterminate"}
                    self._block_dependents(spec_id)
                    continue
                dispatched.handle.status = "completed"
                dispatched.handle.outcome = outcome
                dispatched.handle.integrity_acceptance = acceptance
                self.status_store.update_state(
                    spec_id, "in_progress", run_id=dispatched.run_id,
                    source="coordinator", note="worker result passed terminal integrity gate; awaiting serial integration",
                    payload={"integrity_acceptance": acceptance},
                )
                self._completed.append(dispatched.handle)
                continue
            if success and self.admit_worker is not None:
                dispatched.handle.status = "completed"
                dispatched.handle.outcome = outcome
                self.status_store.update_state(
                    spec_id, "in_progress", run_id=dispatched.run_id,
                    source="coordinator", note="worker completed; awaiting terminal integrity gate and serial integration",
                    payload=outcome,
                )
                self._completed.append(dispatched.handle)
                continue
            self.status_store.update_state(
                spec_id,
                "done" if success else "pending",
                run_id=dispatched.run_id,
                source="coordinator",
                note="worker completed" if success else "worker crashed; recoverable",
                payload=outcome if isinstance(outcome, dict) else {"outcome": str(outcome)},
            )
            if not success:
                failure_outcome = outcome if isinstance(outcome, dict) else {"outcome": str(outcome)}
                self._failed.append({
                    "spec_id": spec_id,
                    "run_id": dispatched.run_id,
                    "reason": str(failure_outcome.get("reason") or "parallel worker failed"),
                    "outcome": failure_outcome,
                })

    def _block_dependents(self, failed_spec_id: str) -> None:
        """Hold only transitive dependents; preserve the divergent worker state."""
        specs = self._load_specs()
        dependencies = {spec.spec_id: set(spec.after) for spec in specs}
        blocked = {failed_spec_id}
        changed = True
        while changed:
            changed = False
            for spec_id, after in dependencies.items():
                if spec_id not in blocked and blocked.intersection(after):
                    blocked.add(spec_id)
                    changed = True
        for spec_id in sorted(blocked - {failed_spec_id}):
            self.status_store.update_state(
                spec_id, "blocked", source="coordinator",
                note=f"held by managed payload drift in {failed_spec_id}",
            )


class MergeStrategy(enum.Enum):
    SEQUENTIAL_MERGE = "SEQUENTIAL_MERGE"
    REBASE_MERGE = "REBASE_MERGE"
    ABORT_ON_CONFLICT = "ABORT_ON_CONFLICT"


@dataclass
class MergeResult:
    """Result of a fan-in merge operation."""

    status: str  # success/partial/conflict/failed
    merged: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    conflicts_detail: List[Tuple[str, str, List[str]]] = field(default_factory=list)
    merge_order: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        data = asdict(self)
        # Convert tuples in conflicts_detail to lists for JSON compat
        data["conflicts_detail"] = [
            list(t) for t in self.conflicts_detail
        ]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "MergeResult":
        """Deserialize from a dict. Never raises; returns safe defaults for missing keys."""
        return cls(
            status=data.get("status", "failed"),
            merged=data.get("merged", []),
            conflicted=data.get("conflicted", []),
            pending=data.get("pending", []),
            conflicts_detail=[
                tuple(item) if isinstance(item, (list, tuple)) else item
                for item in data.get("conflicts_detail", [])
            ],
            merge_order=data.get("merge_order", []),
            error=data.get("error"),
        )


@dataclass
class QueueDecision:
    """Durable record for one coordinator-owned integration decision."""

    spec_id: str
    outcome: str  # accepted/held/reverted
    main_before: str
    main_after: str
    observed_files: List[str] = field(default_factory=list)
    reason: str = ""
    validation_output: str = ""
    queue_wait_s: float = 0.0
    head_drift: bool = False
    rebase_outcome: str = "not_attempted"
    repair_result: str = "not_needed"
    reserved_surfaces: List[str] = field(default_factory=list)
    overlap_kind: str = "none"
    human_status_ping_required: bool = False
    applied_revision: str = ""
    # SPEC-294-001-001 R1: the actual candidate SHA checked against the
    # merge gate (``_merge_validate_or_revert_locked``'s local
    # ``candidate_sha``) -- distinct from ``main_after``, which is the
    # coordinator's own ``HEAD`` and never the candidate. Empty when a
    # decision was produced without ever resolving an authorization-gate
    # candidate ref (e.g. no ``authorization_gate`` configured).
    candidate_sha: str = ""
    # SPEC-278: release-surface lease outcome for this decision.
    # "not_required" | "acquired" | "fail_open" | "contended"
    lease_outcome: str = "not_required"
    lease_warning: str = ""
    revert_attempt_id: int | None = None
    revert_outcome: str = "not_attempted"
    revert_returncode: int | None = None
    merge_attempt_id: int | None = None
    merge_outcome: str = "not_attempted"
    merge_returncode: int | None = None
    merge_recovery_rule: str = "not_required"
    cleanup_outcome: str = "not_attempted"
    cleanup_reason_code: str = ""
    cleanup_resources: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class IntegrationQueueResult:
    """Result of serialized fan-in with per-candidate main evidence."""

    accepted: List[str] = field(default_factory=list)
    held: List[str] = field(default_factory=list)
    reverted: List[str] = field(default_factory=list)
    decisions: List[QueueDecision] = field(default_factory=list)
    integrity_failures: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class CleanupResult:
    """Checked durable disposition of one terminal run's disposable resources."""

    spec_id: str
    run_id: str
    outcome: str  # released | retained | partially_released
    resources: List[Dict[str, Any]]
    reason_code: str
    checkpoint_id: int | None = None
    replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CheckedCleanupProtocol:
    """Sole parent/queue owner for terminal worktree and branch release.

    The status store is outside disposable worktrees.  Every mutation is gated
    by the immutable terminal decision and its durable + tracked projection;
    an append-only started inventory makes command interruption reconcilable.
    """

    def __init__(
        self, repo_root: Path, status_store: StatusStore, *, main_branch: str = "main",
        runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
        after_resource: Optional[Callable[[str, WorktreeHandle], None]] = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.status_store = status_store
        self.main_branch = main_branch
        self.runner = runner or subprocess.run
        self.after_resource = after_resource

    def _git(self, args: List[str]) -> subprocess.CompletedProcess[str]:
        return self.runner(
            ["git", *args], cwd=str(self.repo_root), capture_output=True,
            check=False, text=True,
        )

    def _ref_revision(self, branch: str) -> str | None:
        return self._exact_ref_revision(f"refs/heads/{branch}")

    def _exact_ref_revision(self, ref: str) -> str | None:
        result = self._git(["rev-parse", "--verify", f"{ref}^{{commit}}"])
        revision = result.stdout.strip()
        return revision if result.returncode == 0 and GIT_COMMIT_RE.fullmatch(revision) else None

    def _common_dir(self) -> str:
        result = self._git(["rev-parse", "--path-format=absolute", "--git-common-dir"])
        common_dir = result.stdout.strip()
        if result.returncode != 0 or not common_dir:
            raise StatusStoreError("cannot identify cleanup repository common directory")
        return str(Path(common_dir).resolve())

    def _worktree_registered(self, path: Path) -> bool:
        result = self._git(["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            raise StatusStoreError("cannot inventory linked worktrees before cleanup")
        wanted = self._lexical_path(path)
        return any(
            line == f"worktree {wanted}" for line in result.stdout.splitlines()
        )

    @staticmethod
    def _lexical_path(path: Path) -> str:
        """Return an absolute identity without following the final path entry."""
        return os.path.abspath(os.fspath(path))

    @staticmethod
    def _path_entry(path: Path) -> tuple[str | None, str]:
        """Inspect one exact path with lstat semantics and never follow links."""
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return None, "exact_path_absent"
        except OSError as exc:
            return "ambiguous", f"lstat_failed:{type(exc).__name__}:{exc}"
        if stat.S_ISLNK(mode):
            return "symlink", "unregistered_symlink_at_exact_owner_path"
        if stat.S_ISDIR(mode):
            return "directory", "unregistered_directory_at_exact_owner_path"
        if stat.S_ISREG(mode):
            return "file", "unregistered_file_at_exact_owner_path"
        return "other", "unregistered_special_entry_at_exact_owner_path"

    def _completed_worktree_resource(
        self, owner_path: Path, registered: bool,
    ) -> Dict[str, Any]:
        entry_kind, detail = self._path_entry(owner_path)
        if registered:
            state = "recreated_retained"
            detail = "registered_worktree_recreated"
            try:
                assert_managed_worktree_path(self.repo_root, owner_path)
                assert_worktree_owner(self.repo_root, owner_path)
            except WorktreePathError as exc:
                state = "foreign_or_ambiguous_retained"
                detail = f"registered_owner_ambiguous:{exc}"
            if entry_kind is None:
                state = "ambiguous_retained"
                detail = "registered_worktree_path_missing"
            return {
                "kind": "worktree", "identity": self._lexical_path(owner_path),
                "state": state, "detail": detail,
            }
        if entry_kind is not None:
            return {
                "kind": "worktree", "identity": self._lexical_path(owner_path),
                "state": "ambiguous_retained", "detail": detail,
                "entry_kind": entry_kind,
            }
        return {
            "kind": "worktree", "identity": self._lexical_path(owner_path),
            "state": "released", "detail": detail,
        }

    def _terminal_gate(self, handle: WorktreeHandle) -> tuple[str, Dict[str, Any]]:
        self.status_store.assert_durable_ready()
        run_id = handle.terminal_run_id or handle.integrity_run_id
        if not run_id:
            raise StatusStoreError("cleanup requires terminal run identity")
        decision = self.status_store.get_terminal_decision(handle.spec_id, run_id)
        state = self.status_store.get_state(handle.spec_id)
        if decision is None or state is None:
            raise StatusStoreError("cleanup requires immutable terminal decision and status")
        if (
            state.get("status") != decision.get("decision")
            or state.get("run_id") != run_id
            or (state.get("payload") or {}).get("terminal_decision_id")
                != decision.get("decision_id")
        ):
            raise StatusStoreError("cleanup requires matching durable terminal projection")
        spec_path = Path(handle.canonical_spec_path or "").resolve()
        try:
            relative = spec_path.relative_to(self.repo_root)
        except ValueError as exc:
            raise StatusStoreError("cleanup canonical spec path is outside main") from exc
        from spec_frontmatter import parse_spec_file
        tracked = self._git(["ls-files", "--error-unmatch", relative.as_posix()])
        clean = self._git(["status", "--porcelain", "--", relative.as_posix()])
        if (
            not spec_path.is_file()
            or parse_spec_file(spec_path).frontmatter.get("id") != handle.spec_id
            or parse_spec_file(spec_path).frontmatter.get("status") != decision.get("decision")
            or tracked.returncode != 0
            or clean.returncode != 0
            or clean.stdout.strip()
        ):
            raise StatusStoreError("cleanup requires clean matching tracked frontmatter projection")
        return run_id, decision

    def _owner(self, handle: WorktreeHandle, run_id: str, revision: str) -> Dict[str, str]:
        return {
            "spec_id": handle.spec_id,
            "run_id": run_id,
            "repo_common_dir": self._common_dir(),
            "worktree_path": self._lexical_path(handle.worktree_path),
            "branch_ref": f"refs/heads/{handle.branch_name}",
            "candidate_revision": revision,
        }

    def _record(
        self, handle: WorktreeHandle, run_id: str, *, phase: str,
        owner: Dict[str, str], resources: List[Dict[str, Any]], reason_code: str,
    ) -> Dict[str, Any]:
        return self.status_store.record_cleanup_checkpoint(
            handle.spec_id, run_id, payload={
                "event": "resource_cleanup", "phase": phase,
                "owner": owner, "resources": resources,
                "reason_code": reason_code,
            },
        )

    def cleanup(self, handle: WorktreeHandle) -> CleanupResult:
        run_id, decision = self._terminal_gate(handle)
        history = self.status_store.get_cleanup_history(handle.spec_id, run_id)
        terminal = next(
            (item for item in reversed(history)
             if (item.get("payload") or {}).get("phase") == "completed"),
            None,
        )
        if terminal is not None:
            payload = terminal["payload"]
            owner = payload["owner"]
            owner_branch = str(owner["branch_ref"]).removeprefix("refs/heads/")
            owner_path = Path(owner["worktree_path"])
            registered = self._worktree_registered(owner_path)
            worktree_resource = self._completed_worktree_resource(owner_path, registered)
            identity_matches = (
                owner.get("repo_common_dir") == self._common_dir()
                and self._lexical_path(handle.worktree_path) == owner["worktree_path"]
                and handle.branch_name == owner_branch
                and (
                    handle.verified_revision is None
                    or handle.verified_revision == owner["candidate_revision"]
                )
            )
            branch_revision = self._ref_revision(owner_branch)
            if not identity_matches:
                resources = [
                    worktree_resource,
                    {"kind": "branch", "identity": owner["branch_ref"],
                     "state": "retained" if branch_revision else "released",
                     "revision": branch_revision},
                ]
                checkpoint = self._record(
                    handle, run_id, phase="retained", owner=owner,
                    resources=resources, reason_code="cleanup_retry_owner_mismatch",
                )
                return CleanupResult(
                    handle.spec_id, run_id, "retained", resources,
                    "cleanup_retry_owner_mismatch", checkpoint["checkpoint_id"], True,
                )
            recovery_resources = [
                resource for resource in payload.get("resources", [])
                if resource.get("kind") == "recovery_ref"
            ]
            recovery_drift = any(
                self._exact_ref_revision(str(resource.get("identity")))
                    != resource.get("revision")
                for resource in recovery_resources
            )
            if (
                worktree_resource["state"] != "released"
                or branch_revision is not None
                or recovery_drift
            ):
                resources = [
                    worktree_resource,
                    {"kind": "branch", "identity": owner["branch_ref"],
                     "state": "recreated_retained" if branch_revision else "released",
                     "revision": branch_revision},
                ]
                resources.extend({
                    **resource,
                    "state": (
                        "retained" if self._exact_ref_revision(str(resource["identity"]))
                            == resource.get("revision")
                        else "missing_or_retargeted"
                    ),
                } for resource in recovery_resources)
                checkpoint = self._record(
                    handle, run_id, phase="retained", owner=owner,
                    resources=resources,
                    reason_code=(
                        "cleanup_recovery_ref_missing_or_drift"
                        if recovery_drift
                        else "cleanup_owner_path_occupied"
                        if worktree_resource["state"] == "ambiguous_retained"
                        else "cleanup_resource_recreated"
                    ),
                )
                return CleanupResult(
                    handle.spec_id, run_id, "retained", resources,
                    str(checkpoint["payload"]["reason_code"]),
                    checkpoint["checkpoint_id"], True,
                )
            return CleanupResult(
                handle.spec_id, run_id, "released", list(payload["resources"]),
                str(payload["reason_code"]), terminal["checkpoint_id"], True,
            )

        prior_started = next(
            (item for item in history
             if (item.get("payload") or {}).get("phase") == "started"),
            None,
        )
        branch_revision = self._ref_revision(handle.branch_name)
        prior_owner = (prior_started.get("payload") or {}).get("owner") if prior_started else None
        expected_revision = (
            handle.verified_revision or branch_revision
            or (prior_owner or {}).get("candidate_revision")
        )
        if not expected_revision or not GIT_COMMIT_RE.fullmatch(expected_revision):
            raise StatusStoreError("cleanup candidate revision is unavailable")
        owner = self._owner(handle, run_id, expected_revision)
        if prior_started is not None and (prior_started.get("payload") or {}).get("owner") != owner:
            raise StatusStoreError("cleanup retry owner differs from durable started inventory")
        registered = self._worktree_registered(handle.worktree_path)
        if prior_started is None and (not registered or branch_revision is None):
            resources = [
                {"kind": "worktree", "identity": owner["worktree_path"], "state": "unproven_absent" if not registered else "retained"},
                {"kind": "branch", "identity": owner["branch_ref"], "state": "unproven_absent" if branch_revision is None else "retained", "revision": branch_revision},
            ]
            checkpoint = self._record(
                handle, run_id, phase="retained", owner=owner, resources=resources,
                reason_code="cleanup_initial_inventory_incomplete",
            )
            return CleanupResult(handle.spec_id, run_id, "retained", resources,
                                 "cleanup_initial_inventory_incomplete", checkpoint["checkpoint_id"])
        if branch_revision is not None and branch_revision != expected_revision:
            resources = [
                {"kind": "worktree", "identity": owner["worktree_path"], "state": "retained" if registered else "released"},
                {"kind": "branch", "identity": owner["branch_ref"], "state": "retargeted_retained", "revision": branch_revision},
            ]
            checkpoint = self._record(
                handle, run_id, phase="retained", owner=owner, resources=resources,
                reason_code="cleanup_branch_revision_drift",
            )
            return CleanupResult(handle.spec_id, run_id, "retained", resources,
                                 "cleanup_branch_revision_drift", checkpoint["checkpoint_id"])

        keep_marker = handle.worktree_path / ".nightshift-keep"
        if registered and keep_marker.exists():
            resources = [
                {"kind": "worktree", "identity": owner["worktree_path"], "state": "retained"},
                {"kind": "branch", "identity": owner["branch_ref"], "state": "retained", "revision": branch_revision},
                {"kind": "keep_marker", "identity": str(keep_marker.resolve()), "state": "retained"},
            ]
            checkpoint = self._record(
                handle, run_id, phase="retained", owner=owner, resources=resources,
                reason_code="cleanup_keep_marker_present",
            )
            return CleanupResult(handle.spec_id, run_id, "retained", resources,
                                 "cleanup_keep_marker_present", checkpoint["checkpoint_id"])

        recovery_ref = f"refs/nightshift/recovery/{handle.spec_id}/{run_id}"
        needs_recovery_ref = decision.get("decision") == "blocked"
        if not needs_recovery_ref:
            reachable = self._git([
                "merge-base", "--is-ancestor", expected_revision, self.main_branch,
            ])
            needs_recovery_ref = reachable.returncode != 0
        started_resources = [
            {"kind": "worktree", "identity": owner["worktree_path"], "state": "retained" if registered else "released"},
            {"kind": "branch", "identity": owner["branch_ref"], "state": "retained" if branch_revision else "released", "revision": branch_revision or expected_revision},
        ]
        if needs_recovery_ref:
            started_resources.append({"kind": "recovery_ref", "identity": recovery_ref, "state": "intended", "revision": expected_revision})
        self._record(handle, run_id, phase="started", owner=owner,
                     resources=started_resources, reason_code="cleanup_started")

        if needs_recovery_ref:
            existing = self._git(["rev-parse", "--verify", f"{recovery_ref}^{{commit}}"])
            existing_revision = existing.stdout.strip() if existing.returncode == 0 else None
            if existing_revision not in {None, expected_revision}:
                raise StatusStoreError("cleanup recovery ref is bound to another revision")
            if existing_revision is None:
                created = self._git(["update-ref", recovery_ref, expected_revision, "0" * 40])
                if created.returncode != 0:
                    resources = [
                        {"kind": "worktree", "identity": owner["worktree_path"], "state": "retained"},
                        {"kind": "branch", "identity": owner["branch_ref"], "state": "retained", "revision": branch_revision},
                        {"kind": "recovery_ref", "identity": recovery_ref, "state": "creation_failed"},
                    ]
                    checkpoint = self._record(
                        handle, run_id, phase="retained", owner=owner, resources=resources,
                        reason_code="cleanup_recovery_ref_failed",
                    )
                    return CleanupResult(handle.spec_id, run_id, "retained", resources,
                                         "cleanup_recovery_ref_failed", checkpoint["checkpoint_id"])

        worktree_state = "released"
        worktree_detail = "reconciled_from_started_inventory"
        if registered:
            try:
                assert_managed_worktree_path(self.repo_root, handle.worktree_path)
                assert_worktree_owner(self.repo_root, handle.worktree_path)
            except WorktreePathError as exc:
                worktree_state, worktree_detail = "retained", f"foreign_owner:{exc}"
            else:
                removed = self._git([
                    "worktree", "remove", "--force", str(handle.worktree_path),
                ])
                if removed.returncode != 0:
                    worktree_state = "retained"
                    worktree_detail = removed.stderr.strip() or removed.stdout.strip() or "worktree_remove_failed"
                else:
                    still_registered = self._worktree_registered(handle.worktree_path)
                    if still_registered or handle.worktree_path.exists():
                        worktree_state = "retained"
                        worktree_detail = "worktree_remove_postcondition_mismatch"
                    elif self.after_resource is not None:
                        self.after_resource("worktree", handle)

        current_branch_revision = self._ref_revision(handle.branch_name)
        branch_state = "released"
        branch_detail = "reconciled_from_started_inventory"
        if current_branch_revision is not None:
            if current_branch_revision != expected_revision:
                branch_state, branch_detail = "retargeted_retained", "revision_changed_after_started"
            elif worktree_state != "released":
                branch_state, branch_detail = "retained", "worktree_still_retained"
            else:
                deleted = self._git(["branch", "-D", handle.branch_name])
                if deleted.returncode != 0:
                    branch_state = "retained"
                    branch_detail = deleted.stderr.strip() or deleted.stdout.strip() or "branch_delete_failed"
                elif self._ref_revision(handle.branch_name) is not None:
                    branch_state = "retained"
                    branch_detail = "branch_delete_postcondition_mismatch"
                elif self.after_resource is not None:
                    self.after_resource("branch", handle)

        resources = [
            {"kind": "worktree", "identity": owner["worktree_path"], "state": worktree_state, "detail": worktree_detail},
            {"kind": "branch", "identity": owner["branch_ref"], "state": branch_state, "revision": current_branch_revision or expected_revision, "detail": branch_detail},
        ]
        if needs_recovery_ref:
            resources.append({"kind": "recovery_ref", "identity": recovery_ref, "state": "retained", "revision": expected_revision})
        retained = [resource for resource in resources if resource["state"] != "released" and resource["kind"] != "recovery_ref"]
        outcome = "released" if not retained else "partially_released" if worktree_state == "released" else "retained"
        phase = "completed" if outcome == "released" else "retained"
        reason = "cleanup_released" if outcome == "released" else "cleanup_resources_retained"
        checkpoint = self._record(handle, run_id, phase=phase, owner=owner,
                                  resources=resources, reason_code=reason)
        return CleanupResult(handle.spec_id, run_id, outcome, resources, reason,
                             checkpoint["checkpoint_id"])


def _queue_result_from_record(record: Dict[str, Any]) -> IntegrationQueueResult:
    return IntegrationQueueResult(
        accepted=list(record.get("accepted", [])),
        held=list(record.get("held", [])),
        reverted=list(record.get("reverted", [])),
        decisions=[QueueDecision(**item) for item in record.get("decisions", [])],
        integrity_failures=list(record.get("integrity_failures", [])),
    )


@dataclass
class ReleaseSurfaceLeaseOutcome:
    """Result of one acquisition attempt against the release-surface lease.

    ``status`` is one of ``acquired`` (caller holds the lease; must release),
    ``fail_open`` (the lock mechanism itself was unavailable/erroring; caller
    proceeds today's-behaviour with ``warning`` recorded), or ``contended``
    (a live, healthy holder kept the lease past the bound; caller must not
    proceed into merge).
    """

    status: str
    warning: str = ""
    _handle: Any = field(default=None, repr=False, compare=False)


class ReleaseSurfaceLease:
    """Short-lived, cross-process advisory lease over the release surface.

    SPEC-278: reuses the ``fcntl.flock``-on-a-lockfile pattern already
    established by ``integration_broker.py``'s ``DurableIntegrationReceiptAdapter``,
    rather than inventing a new locking mechanism. One fixed lock file covers
    the release surface as a whole (``canonical/release-manifest.json`` and
    ``canonical/config.yaml``) -- not one lease per protected file, so there is
    no acquisition-order question.
    """

    LOCK_NAME = "release-surface.lock"
    SURFACE: frozenset = frozenset({
        "canonical/release-manifest.json",
        "canonical/config.yaml",
    })

    def __init__(
        self,
        project_root: Path,
        *,
        poll_interval_s: float = 5.0,
        timeout_s: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_root = Path(project_root)
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._sleep = sleep
        self._clock = clock
        self._lock_dir = self.project_root / "reports" / "_wip" / "release-surface-lease"
        self.lock_path = self._lock_dir / self.LOCK_NAME

    def covers(self, paths: Iterable[str]) -> bool:
        """True when any of ``paths`` fall within the protected release surface."""
        return bool(set(paths) & self.SURFACE)

    def acquire(self) -> ReleaseSurfaceLeaseOutcome:
        """Acquire the lease, polling on contention up to ``timeout_s``.

        Fails open (returns ``fail_open`` with a warning) when the lock
        mechanism itself is unavailable or errors -- never when it is simply
        held by a live contender.  A contender still holding the lease past
        the bound yields ``contended``; the caller must not proceed to merge.
        """
        try:
            self._lock_dir.mkdir(parents=True, exist_ok=True)
            handle = open(self.lock_path, "a+b")
        except OSError as exc:
            return ReleaseSurfaceLeaseOutcome(
                status="fail_open",
                warning=f"release-surface lease mechanism unavailable: {exc}",
            )
        start = self._clock()
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return ReleaseSurfaceLeaseOutcome(status="acquired", _handle=handle)
            except BlockingIOError:
                if self._clock() - start >= self.timeout_s:
                    handle.close()
                    return ReleaseSurfaceLeaseOutcome(status="contended")
                self._sleep(self.poll_interval_s)
            except OSError as exc:
                handle.close()
                return ReleaseSurfaceLeaseOutcome(
                    status="fail_open",
                    warning=f"release-surface lease mechanism erroring: {exc}",
                )

    def release(self, outcome: ReleaseSurfaceLeaseOutcome) -> None:
        """Release a held lease. Safe to call on any outcome (R4: every terminal path)."""
        if outcome.status != "acquired" or outcome._handle is None:
            return
        handle = outcome._handle
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()
            outcome._handle = None


class TrackedTerminalFrontmatterProjector:
    """Parent-owned durable-decision to tracked-frontmatter projection."""

    def __init__(
        self, repo_root: Path, status_store: StatusStore, *,
        after_write: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        after_commit: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        commit_runner: Optional[Callable[[List[str]], subprocess.CompletedProcess[str]]] = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.status_store = status_store
        self.repository_identity = self.status_store.require_repository(self.repo_root)
        self.after_write = after_write
        self.after_commit = after_commit
        self.commit_runner = commit_runner

    def _base_projection_contract(
        self, *, base_head: str, relative: str, terminal: str, spec_id: str,
    ) -> tuple[str, str]:
        """Recompute before/target hashes solely from an immutable HEAD blob."""
        from spec_frontmatter import _serialise_frontmatter, _split_frontmatter

        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise StatusStoreError("terminal projection receipt path is unsafe")
        blob = subprocess.run(
            ["git", "show", f"{base_head}:{pure.as_posix()}"],
            cwd=self.repo_root, capture_output=True,
        )
        if blob.returncode != 0:
            raise StatusStoreError("terminal projection receipt base blob is unavailable")
        try:
            text = blob.stdout.decode("utf-8")
            fm_text, body, end_nl = _split_frontmatter(text)
            frontmatter = yaml.safe_load(fm_text) or {}
        except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            raise StatusStoreError("terminal projection receipt base blob is invalid") from exc
        if not isinstance(frontmatter, dict) or frontmatter.get("id") != spec_id:
            raise StatusStoreError("terminal projection receipt spec identity mismatch")
        target_fm = _serialise_frontmatter({**frontmatter, "status": terminal})
        target = (
            f"---\n{target_fm}---\n{body}"
            if end_nl else f"---\n{target_fm}---{body}"
        ).encode("utf-8")
        return hashlib.sha256(blob.stdout).hexdigest(), hashlib.sha256(target).hexdigest()

    def _record_projection(
        self, handle: WorktreeHandle, run_id: str, decision: Dict[str, Any], *,
        phase: str, relative: str, before_sha256: str, expected_sha256: str,
        base_head: str,
    ) -> Dict[str, Any]:
        return self.status_store.record_terminal_projection_event(
            handle.spec_id, run_id, repo_root=self.repo_root, payload={
                "event": "terminal_frontmatter_projection", "phase": phase,
                "decision_id": decision["decision_id"],
                "terminal": decision["decision"], "spec_path": relative,
                "repo_common_dir": self.repository_identity["repo_common_dir"],
                "checkout_root": self.repository_identity["checkout_root"],
                "base_head": base_head,
                "before_sha256": before_sha256,
                "expected_sha256": expected_sha256,
            },
        )

    def _validate_projection_commit(
        self, *, relative: str, expected_sha256: str, base_head: str,
        subject: str, trailers: str,
    ) -> None:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", relative],
            cwd=self.repo_root, capture_output=True, text=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"], cwd=self.repo_root,
            capture_output=True, text=True,
        )
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD^1^{commit}"], cwd=self.repo_root,
            capture_output=True, text=True,
        )
        blob = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=self.repo_root,
            capture_output=True,
        )
        message = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"], cwd=self.repo_root,
            capture_output=True, text=True,
        )
        rendered_message = message.stdout
        if (
            status.returncode != 0
            or status.stdout.strip()
            or head.returncode != 0
            or head.stdout.strip() == base_head
            or parent.returncode != 0
            or parent.stdout.strip() != base_head
            or blob.returncode != 0
            or hashlib.sha256(blob.stdout).hexdigest() != expected_sha256
            or message.returncode != 0
            or rendered_message.splitlines()[0:1] != [subject]
            or any(line not in rendered_message.splitlines() for line in trailers.splitlines())
        ):
            raise RuntimeError("terminal frontmatter commit postcondition failed")

    def validate(self, handle: WorktreeHandle) -> Path:
        path = Path(handle.canonical_spec_path).resolve() if handle.canonical_spec_path else None
        if path is None or not path.is_file():
            raise ValueError(f"canonical spec path missing for {handle.spec_id}")
        try:
            relative = path.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError("canonical spec path is outside the integration checkout") from exc
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            raise ValueError("canonical spec frontmatter is missing")
        parts = content.split("---", 2)
        data = yaml.safe_load(parts[1]) or {}
        if data.get("id") != handle.spec_id:
            raise ValueError("canonical spec path identity mismatch")
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative.as_posix()],
            cwd=self.repo_root, capture_output=True, text=True,
        )
        if tracked.returncode != 0:
            raise ValueError("canonical spec path is not tracked")
        return path

    def project(self, handle: WorktreeHandle, decision: Dict[str, Any]) -> None:
        from spec_frontmatter import parse_spec_file, write_spec_frontmatter

        path = self.validate(handle)
        run_id = handle.terminal_run_id or handle.integrity_run_id
        durable = self.status_store.get_terminal_decision(handle.spec_id, run_id)
        state = self.status_store.get_state(handle.spec_id)
        if (
            durable is None or durable.get("decision_id") != decision.get("decision_id")
            or state is None or state.get("status") != decision.get("decision")
            or state.get("run_id") != run_id
            or (state.get("payload") or {}).get("terminal_decision_id")
                != decision.get("decision_id")
        ):
            raise StatusStoreError("frontmatter projection lacks matching durable terminal state")
        terminal = str(decision["decision"])
        if terminal == "done":
            completion = (decision.get("payload") or {}).get("completion_evidence")
            if (
                not isinstance(completion, dict)
                or completion.get("outcome") != "accepted"
                or completion.get("ok") is not True
                or not isinstance(completion.get("artifacts"), dict)
                or not {"report", "tests", "ac_checklist", "verifier"}.issubset(
                    completion["artifacts"]
                )
            ):
                raise StatusStoreError(
                    "done frontmatter projection lacks parent-accepted completion evidence"
                )
            evidence = ("pass", "pass", "pass", "pass", "pass")
            blocker_class, blocker_scope, resolution = "none", "none", "verifier-dispatched"
        else:
            evidence = ("unknown", "unknown", "unknown", "unknown", "unknown")
            blocker_class, blocker_scope, resolution = "integration", "spec", "blocked"
        trailers = "\n".join((
            f"Nightshift-Evidence-Report: {evidence[0]}",
            f"Nightshift-Evidence-Tests: {evidence[1]}",
            f"Nightshift-Evidence-Code: {evidence[2]}",
            f"Nightshift-Evidence-ACs: {evidence[3]}",
            f"Nightshift-Evidence-Verifier: {evidence[4]}",
            f"Nightshift-Blocker-Class: {blocker_class}",
            f"Nightshift-Blocker-Scope: {blocker_scope}",
            "Nightshift-Unblock-Attempts: 0",
            "Nightshift-Unblock-Limit: 1",
            "Nightshift-Parent-Tool-Calls: 1",
            f"Nightshift-Resolution-Kind: {resolution}",
            "Nightshift-Model: coordinator",
        ))
        subject = f"chore: mark {handle.spec_id} {terminal}"
        current = parse_spec_file(path).frontmatter.get("status")
        relative = path.relative_to(self.repo_root).as_posix()
        path_dirty = bool(subprocess.run(
            ["git", "status", "--porcelain", "--", relative],
            cwd=self.repo_root, capture_output=True, text=True, check=True,
        ).stdout.strip())
        current_bytes = path.read_bytes()
        current_sha256 = hashlib.sha256(current_bytes).hexdigest()
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"], cwd=self.repo_root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        history = self.status_store.get_terminal_projection_history(
            handle.spec_id, run_id,
        )
        latest_payload = history[-1]["payload"] if history else None
        active_receipt = (
            latest_payload
            if isinstance(latest_payload, dict) and latest_payload.get("phase") == "started"
            else None
        )
        base_head = (
            str(active_receipt.get("base_head") or "")
            if active_receipt is not None else current_head
        )
        before_sha256, expected_sha256 = self._base_projection_contract(
            base_head=base_head, relative=relative, terminal=terminal,
            spec_id=handle.spec_id,
        )
        if active_receipt is not None and (
            active_receipt.get("decision_id") != decision.get("decision_id")
            or active_receipt.get("terminal") != terminal
            or active_receipt.get("spec_path") != relative
            or active_receipt.get("repo_common_dir")
                != self.repository_identity["repo_common_dir"]
            or active_receipt.get("checkout_root")
                != self.repository_identity["checkout_root"]
            or active_receipt.get("before_sha256") != before_sha256
            or active_receipt.get("expected_sha256") != expected_sha256
        ):
            raise StatusStoreError(
                "terminal projection receipt conflicts with canonical base target"
            )
        owned_dirty = (
            active_receipt is not None
            and expected_sha256 == current_sha256
        )
        if path_dirty and not owned_dirty:
            raise StatusStoreError(
                "dirty terminal spec path lacks matching parent-owned projection evidence"
            )
        if current == decision["decision"] and not path_dirty:
            if isinstance(latest_payload, dict) and latest_payload.get("phase") == "started":
                if latest_payload.get("expected_sha256") != current_sha256:
                    raise StatusStoreError("clean projection bytes conflict with durable receipt")
                self._validate_projection_commit(
                    relative=relative, expected_sha256=current_sha256,
                    base_head=str(latest_payload.get("base_head") or ""),
                    subject=subject, trailers=trailers,
                )
                self._record_projection(
                    handle, run_id, decision, phase="completed", relative=relative,
                    before_sha256=str(latest_payload.get("before_sha256") or ""),
                    expected_sha256=current_sha256,
                    base_head=str(latest_payload.get("base_head") or ""),
                )
            return
        if not owned_dirty:
            self._record_projection(
                handle, run_id, decision, phase="started", relative=relative,
                before_sha256=before_sha256, expected_sha256=expected_sha256,
                base_head=base_head,
            )
        if current != decision["decision"]:
            write_spec_frontmatter(
                path, lambda frontmatter: {**frontmatter, "status": decision["decision"]},
            )
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
                raise StatusStoreError("terminal projection output differs from durable receipt")
            if self.after_write is not None:
                self.after_write(handle, decision)
        command = [
            "git", "commit", "--only", "-m",
            subject, "-m", trailers,
            "--", relative,
        ]
        if current_head != base_head:
            raise RuntimeError("terminal projection base HEAD changed before commit")
        commit = (
            self.commit_runner(command)
            if self.commit_runner is not None
            else subprocess.run(
                command, cwd=self.repo_root, capture_output=True, text=True,
            )
        )
        if commit.returncode != 0:
            raise RuntimeError(
                f"terminal frontmatter commit failed for {handle.spec_id}: "
                f"{commit.stderr.strip() or commit.stdout.strip()}"
            )
        self._validate_projection_commit(
            relative=relative, expected_sha256=expected_sha256,
            base_head=base_head, subject=subject,
            trailers=trailers,
        )
        if self.after_commit is not None:
            self.after_commit(handle, decision)
        self._record_projection(
            handle, run_id, decision, phase="completed", relative=relative,
            before_sha256=(
                str(latest_payload.get("before_sha256") or "")
                if owned_dirty and isinstance(latest_payload, dict)
                else current_sha256
            ),
            expected_sha256=expected_sha256,
            base_head=base_head,
        )


class SerializedIntegrationQueue:
    """Coordinator-only queue that integrates one completed worktree at a time.

    Workers supply completed branches and may receive bounded repair feedback, but
    this class is the only component that invokes ``git merge`` against main.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        main_branch: str = "main",
        validate_main: Optional[Callable[[WorktreeHandle], Tuple[bool, str]]] = None,
        request_repair: Optional[Callable[[WorktreeHandle, str], bool]] = None,
        status_store: Optional[StatusStore] = None,
        dependency_graph: Optional[Dict[str, Set[str]]] = None,
        max_repair_attempts: int = 1,
        evidence_path: Optional[Path] = None,
        protected_surfaces: Optional[Iterable[str]] = None,
        terminal_gate: Optional[Callable[[WorktreeHandle], Dict[str, Any]]] = None,
        release_surface_lease: Optional[ReleaseSurfaceLease] = None,
        after_terminal_decision: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        after_terminal_status: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        after_revert_attempt: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        after_revert_command: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        revert_runner: Optional[Callable[[WorktreeHandle], subprocess.CompletedProcess[str]]] = None,
        after_merge_failure: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        after_merge_success: Optional[Callable[[WorktreeHandle, Dict[str, Any]], None]] = None,
        merge_runner: Optional[Callable[[WorktreeHandle], subprocess.CompletedProcess[str]]] = None,
        terminal_frontmatter_projector: Any = None,
        cleanup_protocol: CheckedCleanupProtocol | None = None,
        authorization_gate: Optional[Callable[[WorktreeHandle, str, bool], Any]] = None,
    ) -> None:
        if not isinstance(status_store, StatusStore):
            raise StatusStoreError(
                "SerializedIntegrationQueue requires a durable StatusStore"
            )
        status_store.assert_durable_ready()
        if terminal_frontmatter_projector is None:
            raise StatusStoreError(
                "SerializedIntegrationQueue requires a terminal frontmatter projector"
            )
        self.repo_root = Path(repo_root)
        self.main_branch = main_branch
        self.validate_main = validate_main or (lambda _handle: (True, "validation not configured"))
        self.request_repair = request_repair
        self.status_store = status_store
        self.dependency_graph = dependency_graph or {}
        self.max_repair_attempts = max(0, max_repair_attempts)
        self.evidence_path = Path(evidence_path) if evidence_path else None
        self.protected_surfaces = set(protected_surfaces or ())
        self._reservations: Dict[str, Set[str]] = {}
        # Retained across per-handle calls so coordinator exception isolation
        # does not weaken cross-candidate overlap checks.
        self._accepted_files: Set[str] = set()
        self._accepted_declared: Set[str] = set()
        self._restored_terminal_decisions: Set[Tuple[str, str, int]] = set()
        self._session_evidence = IntegrationQueueResult()
        self._last_rebase_conflicts: List[str] = []
        self.terminal_gate = terminal_gate
        self._shared_integrity_failure: Dict[str, str] | None = None
        self._revert_failure: Dict[str, Any] | None = None
        # SPEC-278: optional release-surface lease guarding the
        # merge-and-regenerate window for manifest-touching candidates.
        self.release_surface_lease = release_surface_lease
        # Testable crash seam after durable choice and before projection.  The
        # hook cannot choose or mutate the decision.
        self.after_terminal_decision = after_terminal_decision
        self.after_terminal_status = after_terminal_status
        self.after_revert_attempt = after_revert_attempt
        self.after_revert_command = after_revert_command
        self.revert_runner = revert_runner
        self.after_merge_failure = after_merge_failure
        self.after_merge_success = after_merge_success
        self.merge_runner = merge_runner
        self.terminal_frontmatter_projector = terminal_frontmatter_projector
        self.cleanup_protocol = cleanup_protocol or CheckedCleanupProtocol(
            self.repo_root, status_store, main_branch=main_branch,
        )
        # SPEC-294 R3/R6: optional deployment-environment authorization
        # gate. ``None`` (the default) is exactly today's behavior -- no new
        # code path runs, no config/frontmatter is read, R2 is mechanical
        # rather than conventional. Mirrors ``request_repair``'s injected-
        # callable shape: config/frontmatter reading stays out of the queue,
        # so this remains the sole merge owner (NFR-001 I2) with no new
        # writer or dispatch path (R6).  Signature:
        # ``gate(handle, candidate_sha, head_drift) -> AuthorizationStatus``.
        self.authorization_gate = authorization_gate

    def cleanup_terminal_resources(self, handle: WorktreeHandle) -> CleanupResult:
        """Release one exact terminal run without changing its terminal facts."""
        try:
            return self.cleanup_protocol.cleanup(handle)
        except (OSError, subprocess.SubprocessError, WorktreePathError,
                StatusStoreError, ValueError) as exc:
            run_id = self._terminal_run_id(handle)
            resources = [
                {"kind": "worktree", "identity": str(handle.worktree_path),
                 "state": "retained", "detail": str(exc)},
                {"kind": "branch", "identity": f"refs/heads/{handle.branch_name}",
                 "state": "retained", "revision": handle.verified_revision},
            ]
            checkpoint = self.status_store.record_cleanup_checkpoint(
                handle.spec_id, run_id, payload={
                    "event": "resource_cleanup", "phase": "retained",
                    "owner": {
                        "spec_id": handle.spec_id, "run_id": run_id,
                        "worktree_path": str(handle.worktree_path),
                        "branch_ref": f"refs/heads/{handle.branch_name}",
                        "candidate_revision": handle.verified_revision or "unknown",
                    },
                    "resources": resources,
                    "reason_code": "cleanup_precondition_failed",
                },
            )
            return CleanupResult(
                handle.spec_id, run_id, "retained", resources,
                "cleanup_precondition_failed", checkpoint["checkpoint_id"],
            )

    @property
    def shared_integrity_failed(self) -> bool:
        return self._shared_integrity_failure is not None

    def _record_shared_integrity_failure(self, reason_code: str) -> None:
        """Record exactly one run-level failure without terminalizing workers."""
        if self._shared_integrity_failure is None:
            self._shared_integrity_failure = {
                "event": "managed_payload_integrity_failed",
                "reason_code": reason_code,
                "scope": "shared",
            }

    def reserve(self, handle: WorktreeHandle) -> List[str]:
        """Reserve declared and release surfaces before a worker is dispatched.

        The return value names existing owners that overlap.  Reservations are
        deliberately local to one coordinator and are evidence, not a lock.
        """
        surfaces = set(handle.declared_touches) | self.protected_surfaces
        conflicts = sorted({owner for owner, claimed in self._reservations.items()
                            if owner != handle.spec_id and self._surface_overlap(surfaces, claimed)})
        if not conflicts:
            self._reservations[handle.spec_id] = surfaces
        return conflicts

    def release(self, spec_id: str) -> None:
        """Release a terminal reservation without touching a worker tree."""
        self._reservations.pop(spec_id, None)

    def integrate(
        self,
        handles: Iterable[WorktreeHandle],
        *,
        operation_key: str | None = None,
        operation_digest: str | None = None,
    ) -> IntegrationQueueResult:
        """Integrate compatible completed handles in deterministic spec-ID order."""
        # Re-check at the mutation boundary: the store may have become
        # unavailable after construction, and no Git effect may precede this.
        self.status_store.assert_durable_ready()
        self._revert_failure = self._scan_durable_revert_barrier()
        materialized = list(handles)
        if (operation_key is None) != (operation_digest is None):
            raise ValueError("integration operation identity is incomplete")
        if operation_key is not None and self.evidence_path is None:
            raise ValueError("durable queue evidence is required for keyed integration")
        if operation_key is not None and len(materialized) != 1:
            raise ValueError("keyed integration requires exactly one handle")
        prepared: Dict[str, Any] | None = None
        if operation_key is not None and self.evidence_path is not None:
            prior = _read_keyed_queue_record(
                self.evidence_path, operation_key, operation_digest
            )
            if prior is not None:
                if prior.get("phase") == "terminal":
                    return _queue_result_from_record(prior)
                if prior.get("phase") != "prepared":
                    raise ValueError("durable integration queue phase is invalid")
                prepared = prior
                reconciled = self._reconcile_prepared_operation(
                    materialized[0], prior,
                    operation_key=operation_key,
                    operation_digest=operation_digest,
                )
                if reconciled is not None:
                    return reconciled
        result = IntegrationQueueResult()
        accepted_files = self._accepted_files
        accepted_declared = self._accepted_declared
        shared_integrity_failure = (
            self._shared_integrity_failure["reason_code"]
            if self._shared_integrity_failure is not None else None
        )
        for handle in sorted((h for h in materialized if h.status == "completed"), key=lambda h: h.spec_id):
            # A fresh queue is not the only restart boundary: another process
            # may have appended an attempt while this batch was draining.
            self._revert_failure = self._scan_durable_revert_barrier()
            self.terminal_frontmatter_projector.validate(handle)
            queued_at = time.monotonic()
            recovered_terminal = (
                None if self._handle_owns_revert_barrier(handle)
                else self._recover_existing_terminal(handle)
            )
            if recovered_terminal is not None:
                result.accepted.extend(recovered_terminal.accepted)
                result.held.extend(recovered_terminal.held)
                result.reverted.extend(recovered_terminal.reverted)
                result.decisions.extend(recovered_terminal.decisions)
                continue
            barrier = self._revert_barrier_for(handle)
            recovered_revert = (
                self._recover_checked_revert(handle) if barrier is None else None
            )
            if recovered_revert is not None:
                result.accepted.extend(recovered_revert.accepted)
                result.held.extend(recovered_revert.held)
                result.reverted.extend(recovered_revert.reverted)
                result.decisions.extend(recovered_revert.decisions)
                self._revert_failure = self._scan_durable_revert_barrier()
                continue
            before = self._head()
            if shared_integrity_failure is not None:
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(
                    handle.spec_id, "held", before, before,
                    reason=f"shared_managed_payload_integrity:{shared_integrity_failure}",
                    reserved_surfaces=sorted(self._reservations.get(handle.spec_id, set(handle.declared_touches))),
                ))
                continue
            barrier = self._revert_barrier_for(handle)
            if barrier is not None:
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(
                    handle.spec_id, "held", before, before,
                    reason="shared_main_revert_recovery_required",
                    reserved_surfaces=sorted(
                        self._reservations.get(handle.spec_id, set(handle.declared_touches))
                    ),
                ))
                continue
            recovered_terminal = self._recover_existing_terminal(
                handle, project_if_needed=True,
            )
            if recovered_terminal is not None:
                result.accepted.extend(recovered_terminal.accepted)
                result.held.extend(recovered_terminal.held)
                result.reverted.extend(recovered_terminal.reverted)
                result.decisions.extend(recovered_terminal.decisions)
                continue
            reserved = sorted(
                self._reservations.get(handle.spec_id, set(handle.declared_touches))
            )
            recovered_merge = self._recover_merge_failure(handle, reserved)
            if recovered_merge is not None:
                result.accepted.extend(recovered_merge.accepted)
                result.held.extend(recovered_merge.held)
                result.reverted.extend(recovered_merge.reverted)
                result.decisions.extend(recovered_merge.decisions)
                if recovered_merge.accepted:
                    accepted_files.update(recovered_merge.decisions[0].observed_files)
                    accepted_declared.update(handle.declared_touches)
                continue
            dirty = self._main_is_dirty()
            if dirty:
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(
                    handle.spec_id, "held", before, before, reason="main_dirty_external",
                    queue_wait_s=time.monotonic() - queued_at, reserved_surfaces=reserved,
                    human_status_ping_required=True,
                ))
                continue
            try:
                _assert_handle_ownership_if_present(handle, self.repo_root)
            except WorktreePathError as exc:
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(handle.spec_id, "held", before, before, reason=str(exc), reserved_surfaces=reserved))
                continue
            revision_error = self._verified_revision_error(handle)
            if revision_error:
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(
                    handle.spec_id, "held", before, before,
                    reason=revision_error, reserved_surfaces=reserved,
                ))
                continue
            if self.terminal_gate is not None:
                acceptance = self.terminal_gate(handle)
                handle.integrity_acceptance = acceptance
                if not isinstance(acceptance, dict) or not acceptance.get("ok"):
                    result.held.append(handle.spec_id)
                    reason_code = acceptance.get("reason_code", "NS-MPI-INDETERMINATE") if isinstance(acceptance, dict) else "NS-MPI-INDETERMINATE"
                    result.decisions.append(QueueDecision(
                        handle.spec_id, "held", before, before,
                        reason=f"managed_payload_integrity:{reason_code}",
                        reserved_surfaces=reserved,
                    ))
                    if isinstance(acceptance, dict) and acceptance.get("scope") == "shared":
                        shared_integrity_failure = reason_code
                        self._record_shared_integrity_failure(reason_code)
                    else:
                        self._block_dependents(handle.spec_id)
                    continue
            integration_ref = handle.verified_revision or handle.branch_name
            resolved_integration_revision = self._git(
                ["rev-parse", "--verify", f"{integration_ref}^{{commit}}"]
            ).stdout.strip()
            observed = self._changed_files(integration_ref)
            protected = sorted(set(observed) & self.protected_surfaces)
            intents = {str(intent.get("path", "")) for intent in handle.release_intents if isinstance(intent, dict)}
            if protected and not set(protected).issubset(intents):
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(
                    handle.spec_id, "held", before, before, observed,
                    "protected_release_surface_without_intent: " + ", ".join(protected),
                    reserved_surfaces=reserved, overlap_kind="protected_release_surface",
                    human_status_ping_required=True,
                ))
                continue
            declared = set(handle.declared_touches)
            overlap = sorted(accepted_files & set(observed))
            declared_overlap = self._surface_overlap(declared, accepted_declared)
            if overlap or declared_overlap:
                reason = "actual changed-file overlap: " + ", ".join(overlap or declared_overlap)
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(handle.spec_id, "held", before, before, observed, reason, reserved_surfaces=reserved, overlap_kind="declared_or_observed"))
                continue

            if operation_key is not None and self.evidence_path is not None:
                intent = {
                    "phase": "prepared",
                    "operation_key": operation_key,
                    "operation_digest": operation_digest,
                    "spec_id": handle.spec_id,
                    "main_before": before,
                    "candidate_revision": resolved_integration_revision,
                    "declared_surfaces": sorted(handle.declared_touches),
                    "observed_files": observed,
                    "reserved_surfaces": reserved,
                }
                if prepared is not None and prepared != intent:
                    raise ValueError("divergent prepared integration operation")
                if prepared is None:
                    write_prepared_integration_intent(intent, self.evidence_path)
                    prepared = intent

            # A verified Git object is already the content accepted by the
            # independent checker.  Rebasing would manufacture a different
            # object; merge that immutable object directly into fresh main.
            if handle.verified_revision:
                rebased, rebase_outcome = True, "verified_revision_pinned"
            else:
                rebased, rebase_outcome = self._rebase(handle)
            if not rebased:
                repaired = False
                if self.max_repair_attempts and self.request_repair:
                    repaired = bool(self.request_repair(handle, {
                        "kind": "rebase_conflict",
                        "paths": self._last_rebase_conflicts,
                        "base_ref": self.main_branch,
                        "worker_ref": handle.branch_name,
                    }))
                    if repaired:
                        rebased, rebase_outcome = self._rebase(handle)
                if rebased:
                    accepted = self._merge_validate_or_revert(handle, before, observed, result, queue_wait_s=time.monotonic() - queued_at, head_drift=True, rebase_outcome=rebase_outcome, reserved_surfaces=reserved)
                    if accepted:
                        accepted_files.update(observed)
                        accepted_declared.update(declared)
                        self.release(handle.spec_id)
                    continue
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(handle.spec_id, "held", before, self._head(), observed, "reconciliation failed", reserved_surfaces=reserved, rebase_outcome=rebase_outcome, repair_result="requested" if repaired else "failed", human_status_ping_required=True))
                continue

            accepted = self._merge_validate_or_revert(
                handle, before, observed, result,
                queue_wait_s=time.monotonic() - queued_at,
                head_drift=before != self._head(),
                rebase_outcome=rebase_outcome,
                reserved_surfaces=reserved,
                applied_revision=resolved_integration_revision,
            )
            if accepted:
                accepted_files.update(observed)
                accepted_declared.update(declared)
                self.release(handle.spec_id)
        result.integrity_failures = list(
            [self._shared_integrity_failure] if self._shared_integrity_failure else []
        )
        if self.evidence_path is not None:
            evidence_result = result
            if operation_key is None:
                self._session_evidence.accepted.extend(result.accepted)
                self._session_evidence.held.extend(result.held)
                self._session_evidence.reverted.extend(result.reverted)
                self._session_evidence.decisions.extend(result.decisions)
                self._session_evidence.integrity_failures = list(result.integrity_failures)
                evidence_result = self._session_evidence
            write_integration_queue_result(
                evidence_result,
                self.evidence_path,
                operation_key=operation_key,
                operation_digest=operation_digest,
            )
        return result

    def _reconcile_prepared_operation(
        self, handle: WorktreeHandle, intent: Dict[str, Any], *,
        operation_key: str, operation_digest: str | None,
    ) -> IntegrationQueueResult | None:
        """Recover a keyed merge whose terminal queue evidence was interrupted."""
        recovered_terminal = (
            None if self._handle_owns_revert_barrier(handle)
            else self._recover_existing_terminal(handle)
        )
        if recovered_terminal is not None:
            assert self.evidence_path is not None
            write_integration_queue_result(
                recovered_terminal, self.evidence_path,
                operation_key=operation_key, operation_digest=operation_digest,
            )
            return recovered_terminal
        barrier = self._revert_barrier_for(handle)
        recovered_revert = (
            self._recover_checked_revert(handle) if barrier is None else None
        )
        if recovered_revert is not None:
            assert self.evidence_path is not None
            write_integration_queue_result(
                recovered_revert, self.evidence_path,
                operation_key=operation_key, operation_digest=operation_digest,
            )
            return recovered_revert
        self._revert_failure = self._scan_durable_revert_barrier()
        barrier = self._revert_barrier_for(handle)
        if barrier is not None:
            head = self._head()
            held = IntegrationQueueResult(
                held=[handle.spec_id],
                decisions=[QueueDecision(
                    handle.spec_id, "held", head, head,
                    reason="shared_main_revert_recovery_required",
                    reserved_surfaces=list(intent.get("reserved_surfaces", [])),
                )],
            )
            assert self.evidence_path is not None
            write_integration_queue_result(
                held, self.evidence_path,
                operation_key=operation_key, operation_digest=operation_digest,
            )
            return held
        recovered_terminal = self._recover_existing_terminal(
            handle, project_if_needed=True,
        )
        if recovered_terminal is not None:
            assert self.evidence_path is not None
            write_integration_queue_result(
                recovered_terminal, self.evidence_path,
                operation_key=operation_key, operation_digest=operation_digest,
            )
            return recovered_terminal
        revision = handle.verified_revision
        raw_observed = intent.get("observed_files")
        raw_declared = intent.get("declared_surfaces")

        def canonical_surfaces(
            value: Any, *, allow_directory_marker: bool = False,
        ) -> bool:
            return (
                isinstance(value, list)
                and all(
                    is_canonical_repository_relative_path(
                        path, allow_directory_marker=allow_directory_marker,
                    )
                    for path in value
                )
                and value == sorted(set(value))
            )

        observed_contract_valid = (
            isinstance(raw_observed, list)
            and canonical_surfaces(raw_observed)
        )
        declared_contract_valid = canonical_surfaces(
            raw_declared, allow_directory_marker=True,
        )
        raw_reserved = intent.get("reserved_surfaces")
        reserved_contract_valid = canonical_surfaces(
            raw_reserved, allow_directory_marker=True,
        )
        observed = list(raw_observed) if observed_contract_valid else []
        handle_contract_valid = canonical_surfaces(
            handle.declared_touches, allow_directory_marker=True,
        )
        handle_declared = list(handle.declared_touches) if handle_contract_valid else []
        reserved = list(raw_reserved) if reserved_contract_valid else []
        intent_revision = intent.get("candidate_revision")
        expected = {
            "operation_key": operation_key,
            "operation_digest": operation_digest,
            "spec_id": handle.spec_id,
        }
        if any(intent.get(key) != value for key, value in expected.items()):
            raise ValueError("divergent prepared integration operation")
        before = intent.get("main_before")
        if not isinstance(before, str) or not GIT_COMMIT_RE.fullmatch(before):
            raise ValueError("prepared integration main identity is invalid")
        current = self._head()
        merge_history = self.status_store.get_merge_attempt_history(
            handle.spec_id, self._terminal_run_id(handle),
        )
        if not merge_history and current == before:
            return None
        latest_merge = merge_history[-1] if merge_history else None
        merge_payload = (latest_merge or {}).get("payload") or {}
        run_id = self._terminal_run_id(handle)
        ledger_observed = merge_payload.get("observed_files")
        ledger_declared = merge_payload.get("declared_surfaces")
        ledger_conflicts = merge_payload.get("conflict_files")
        ledger_surfaces_valid = (
            canonical_surfaces(ledger_observed)
            and canonical_surfaces(
                ledger_declared, allow_directory_marker=True,
            )
            and canonical_surfaces(ledger_conflicts)
        )
        identity_matches = (
            isinstance(revision, str)
            and revision == intent_revision
            and observed_contract_valid
            and declared_contract_valid
            and reserved_contract_valid
            and handle_contract_valid
            and raw_declared == handle_declared
            and ledger_surfaces_valid
            and ledger_observed == raw_observed
            and ledger_declared == raw_declared
            and latest_merge is not None
            and latest_merge.get("spec_id") == handle.spec_id
            and latest_merge.get("run_id") == run_id
            and merge_payload.get("candidate_revision") == intent_revision
            and merge_payload.get("main_before") == before
            and isinstance(merge_payload.get("attempt_number"), int)
            and not isinstance(merge_payload.get("attempt_number"), bool)
            and merge_payload.get("attempt_number") in {1, 2}
        )
        semantically_applied, current, application_detail = (
            self._merge_application_state(before, str(intent_revision or ""))
            if identity_matches else
            (False, current, "prepared/ledger merge identity mismatch")
        )
        outcome = merge_payload.get("outcome")
        if latest_merge is not None and outcome == "started" \
                and ledger_surfaces_valid:
            if semantically_applied:
                latest_merge = self.status_store.record_merge_attempt(
                    handle.spec_id, self._terminal_run_id(handle), payload={
                        **merge_payload, "outcome": "succeeded",
                        "reason_code": "NS-INTEGRATION-MERGE-SUCCEEDED",
                        "recovery_rule": "continue_validation",
                        "main_after": current, "returncode": 0,
                        "started_event_id": latest_merge["event_id"],
                        "application_proof": application_detail,
                    },
                )
            elif identity_matches and current == before \
                    and not self._main_has_external_dirty_state():
                self.status_store.record_merge_attempt(
                    handle.spec_id, self._terminal_run_id(handle), payload={
                        **merge_payload, "outcome": "interrupted",
                        "reason_code": "NS-INTEGRATION-MERGE-INTERRUPTED",
                        "recovery_rule": "retry_once_on_restart",
                        "main_after": current,
                        "stderr": application_detail,
                        "started_event_id": latest_merge["event_id"],
                    },
                )
                return None
            else:
                latest_merge = self.status_store.record_merge_attempt(
                    handle.spec_id, self._terminal_run_id(handle), payload={
                        **merge_payload, "outcome": "recovery_required",
                        "reason_code": "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED",
                        "recovery_rule": "restore_exact_main_then_retry_once",
                        "main_after": current,
                        "stderr": application_detail,
                        "started_event_id": latest_merge["event_id"],
                    },
                )
        elif latest_merge is not None and outcome == "succeeded" \
                and ledger_surfaces_valid and not semantically_applied:
            latest_merge = self.status_store.record_merge_attempt(
                handle.spec_id, self._terminal_run_id(handle), payload={
                    **merge_payload, "outcome": "recovery_required",
                    "reason_code": "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED",
                    "recovery_rule": "restore_exact_main_then_retry_once",
                    "main_after": current,
                    "stderr": "\n".join(filter(None, (
                        str(merge_payload.get("stderr") or ""), application_detail,
                    ))),
                    "reconciled_event_id": latest_merge["event_id"],
                },
            )
        if semantically_applied and latest_merge is not None \
                and (latest_merge.get("payload") or {}).get("outcome") == "succeeded":
            passed, output = self.validate_main(handle)
            if passed:
                handle.status = "accepted"
                self._project_terminal_status(
                    handle, "done",
                    "accepted by recovered serialized integration queue",
                    observed=observed, declared=handle.declared_touches,
                )
                cleanup = self.cleanup_terminal_resources(handle)
                self.release(handle.spec_id)
                result = IntegrationQueueResult(
                    accepted=[handle.spec_id],
                    decisions=[QueueDecision(
                        handle.spec_id, "accepted", before, current, observed,
                        validation_output=output,
                        rebase_outcome="verified_revision_pinned",
                        reserved_surfaces=reserved,
                        applied_revision=revision,
                        cleanup_outcome=cleanup.outcome,
                        cleanup_reason_code=cleanup.reason_code,
                        cleanup_resources=cleanup.resources,
                        **self._merge_fields(latest_merge),
                    )],
                )
                assert self.evidence_path is not None
                write_integration_queue_result(
                    result, self.evidence_path,
                    operation_key=operation_key,
                    operation_digest=operation_digest,
                )
                return result
            attempt = self._checked_revert(handle, before, current, observed)
            result = self._classify_checked_revert(
                handle, attempt, observed, output,
                rebase_outcome="verified_revision_pinned",
                reserved_surfaces=reserved,
            )
            assert self.evidence_path is not None
            write_integration_queue_result(
                result, self.evidence_path,
                operation_key=operation_key,
                operation_digest=operation_digest,
            )
            return result
        failure_reason = (
            "NS-INTEGRATION-MERGE-RECOVERY-IDENTITY-MISMATCH"
            if not identity_matches
            else "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED"
        )
        result = IntegrationQueueResult(
            held=[handle.spec_id],
            decisions=[QueueDecision(
                handle.spec_id, "held", before, current, observed,
                reason=failure_reason,
                reserved_surfaces=reserved,
                human_status_ping_required=True,
                **(self._merge_fields(latest_merge) if latest_merge else {}),
            )],
        )
        assert self.evidence_path is not None
        write_integration_queue_result(
            result, self.evidence_path,
            operation_key=operation_key,
            operation_digest=operation_digest,
        )
        return result

    @staticmethod
    def _revert_fields(attempt: Dict[str, Any]) -> Dict[str, Any]:
        payload = attempt.get("payload") or {}
        return {
            "revert_attempt_id": attempt.get("checkpoint_id"),
            "revert_outcome": str(payload.get("outcome") or "unknown"),
            "revert_returncode": payload.get("returncode"),
        }

    def _scan_durable_revert_barrier(self) -> Dict[str, Any] | None:
        """Bind only unresolved attempts whose candidate still affects current main."""
        current = self._head()
        blockers: List[Dict[str, Any]] = []
        for attempt in self.status_store.list_latest_revert_attempts():
            payload = attempt.get("payload") or {}
            spec_id = attempt.get("spec_id")
            run_id = attempt.get("run_id")
            merge_revision = payload.get("merge_revision")
            main_before = payload.get("main_before")
            outcome = payload.get("outcome")
            hashes_valid = all(
                isinstance(value, str) and GIT_COMMIT_RE.fullmatch(value)
                for value in (merge_revision, main_before)
            )
            if not hashes_valid:
                continue
            first_parent = self._git(["rev-parse", f"{merge_revision}^1"])
            if first_parent.returncode != 0 or first_parent.stdout.strip() != main_before:
                continue
            merge_is_ancestor = self._git([
                "merge-base", "--is-ancestor", merge_revision, current,
            ]).returncode == 0
            if not merge_is_ancestor:
                continue

            observed = payload.get("observed_files")
            observed_valid = (
                isinstance(observed, list)
                and bool(observed)
                and all(
                    isinstance(path, str)
                    and path
                    and not Path(path).is_absolute()
                    and ".." not in Path(path).parts
                    for path in observed
                )
            )
            main_after = payload.get("main_after")
            successful = outcome == "succeeded"
            if successful:
                success_valid = (
                    isinstance(main_after, str)
                    and GIT_COMMIT_RE.fullmatch(main_after) is not None
                    and self._git(["rev-parse", f"{main_after}^1"]).stdout.strip()
                    == merge_revision
                    and self._git([
                        "diff", "--quiet", main_before, main_after,
                    ]).returncode == 0
                )
                if success_valid:
                    # Main safety is restored by the checked revert itself;
                    # terminal projection is a distinct idempotent concern.
                    continue

            parent = self._git(["rev-parse", f"{current}^1"])
            direct_child = (
                current != merge_revision
                and parent.returncode == 0
                and parent.stdout.strip() == merge_revision
            )
            observed_delta = False
            if observed_valid:
                observed_delta = self._git([
                    "diff", "--quiet", main_before, current, "--", *observed,
                ]).returncode != 0
            bound = (
                current == merge_revision
                or direct_child
                or observed_delta
            )
            if not bound:
                continue
            blockers.append({
                "spec_id": spec_id,
                "run_id": run_id,
                "checkpoint_id": attempt.get("checkpoint_id"),
                "reason_code": payload.get("reason_code"),
                "outcome": outcome,
                "merge_revision": merge_revision,
                "main_before": main_before,
                "observed_files": list(observed) if observed_valid else [],
            })
        if not blockers:
            return None
        return {"blockers": blockers, **blockers[0]}

    def _revert_barrier_for(self, handle: WorktreeHandle) -> Dict[str, Any] | None:
        barrier = self._revert_failure
        if barrier is None:
            return None
        blockers = barrier.get("blockers") or [barrier]
        for blocker in blockers:
            owner = (
                blocker.get("spec_id") == handle.spec_id
                and blocker.get("run_id") == self._terminal_run_id(handle)
            )
            if not owner:
                return blocker
        return None

    def _handle_owns_revert_barrier(self, handle: WorktreeHandle) -> bool:
        barrier = self._revert_failure
        if barrier is None:
            return False
        blockers = barrier.get("blockers") or [barrier]
        return any(
            blocker.get("spec_id") == handle.spec_id
            and blocker.get("run_id") == self._terminal_run_id(handle)
            for blocker in blockers
        )

    def _recover_existing_terminal(
        self, handle: WorktreeHandle, *, project_if_needed: bool = False,
    ) -> IntegrationQueueResult | None:
        run_id = self._terminal_run_id(handle)
        decision = self.status_store.get_terminal_decision(handle.spec_id, run_id)
        if decision is None:
            return None
        payload = decision.get("payload") or {}
        observed = payload.get("observed_files")
        declared = payload.get("declared_surfaces")
        if (
            not isinstance(observed, list)
            or not all(isinstance(path, str) for path in observed)
            or not isinstance(declared, list)
            or not all(isinstance(path, str) for path in declared)
        ):
            raise ValueError("terminal decision surface evidence is missing or invalid")
        if project_if_needed:
            terminal = self.recover_terminal_projection(
                handle, record_evidence=False,
            )
        else:
            from spec_frontmatter import parse_spec_file

            spec_path = self.terminal_frontmatter_projector.validate(handle)
            if not isinstance(spec_path, Path):
                return None
            state = self.status_store.get_state(handle.spec_id)
            projected = (
                state is not None
                and state.get("status") == decision.get("decision")
                and state.get("run_id") == run_id
                and (state.get("payload") or {}).get("terminal_decision_id")
                    == decision.get("decision_id")
                and parse_spec_file(spec_path).frontmatter.get("status")
                    == decision.get("decision")
            )
            relative = spec_path.relative_to(self.repo_root)
            path_clean = self._git([
                "status", "--porcelain", "--", relative.as_posix(),
            ]).stdout.strip() == ""
            if not projected or not path_clean:
                return None
            terminal = str(decision["decision"])
            if terminal == "done":
                self.restore_accepted_terminal_decision(
                    handle.spec_id, decision,
                )
                handle.status = "accepted"
                self.release(handle.spec_id)
            else:
                handle.status = "failed"
        head = self._head()
        outcome = "accepted" if terminal == "done" else "reverted"
        return IntegrationQueueResult(
            accepted=[handle.spec_id] if terminal == "done" else [],
            reverted=[handle.spec_id] if terminal == "blocked" else [],
            decisions=[QueueDecision(
                handle.spec_id, outcome, head, head, observed,
                reason="immutable_terminal_projection_recovered",
                validation_output=str(payload.get("validation_output") or ""),
                applied_revision=handle.verified_revision or "",
            )],
        )

    def _checked_revert(
        self, handle: WorktreeHandle, main_before: str, merge_revision: str,
        observed: Iterable[str],
    ) -> Dict[str, Any]:
        """Run and durably record one exact revert attempt before disposition."""
        started = self.status_store.record_revert_attempt(
            handle.spec_id, self._terminal_run_id(handle), payload={
                "outcome": "started",
                "reason_code": "NS-INTEGRATION-REVERT-STARTED",
                "main_before": main_before,
                "merge_revision": merge_revision,
                "main_after": merge_revision,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "observed_files": sorted(set(observed)),
                "declared_surfaces": sorted(set(handle.declared_touches)),
            },
        )
        try:
            reverted = (
                self.revert_runner(handle)
                if self.revert_runner is not None
                else self._git(["revert", "-m", "1", merge_revision, "--no-edit"])
            )
            returncode = reverted.returncode
            stdout = reverted.stdout or ""
            stderr = reverted.stderr or ""
            if returncode == 0:
                current = self._head()
                parent = self._git(["rev-parse", f"{current}^"])
                tree_matches = self._git([
                    "diff", "--exit-code", main_before, current,
                ])
                postcondition_ok = (
                    current != merge_revision
                    and parent.returncode == 0
                    and parent.stdout.strip() == merge_revision
                    and tree_matches.returncode == 0
                    and not self._main_is_dirty()
                )
                outcome = "succeeded" if postcondition_ok else "postcondition_mismatch"
                reason_code = (
                    "NS-INTEGRATION-REVERT-SUCCEEDED"
                    if postcondition_ok
                    else "NS-INTEGRATION-REVERT-POSTCONDITION-MISMATCH"
                )
            else:
                outcome = "failed"
                reason_code = "NS-INTEGRATION-REVERT-FAILED"
        except (Exception, KeyboardInterrupt) as exc:
            returncode = None
            stdout = ""
            stderr = f"{type(exc).__name__}: {exc}"
            outcome = "interrupted"
            reason_code = "NS-INTEGRATION-REVERT-INTERRUPTED"
        if self.after_revert_command is not None:
            self.after_revert_command(handle, started)
        attempt = self.status_store.record_revert_attempt(
            handle.spec_id, self._terminal_run_id(handle), payload={
                "outcome": outcome,
                "reason_code": reason_code,
                "main_before": main_before,
                "merge_revision": merge_revision,
                "main_after": self._head(),
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "observed_files": sorted(set(observed)),
                "declared_surfaces": sorted(set(handle.declared_touches)),
                "started_checkpoint_id": started["checkpoint_id"],
            },
        )
        if self.after_revert_attempt is not None:
            self.after_revert_attempt(handle, attempt)
        return attempt

    def _classify_checked_revert(
        self, handle: WorktreeHandle, attempt: Dict[str, Any],
        observed: List[str], validation_output: str, **evidence: Any,
    ) -> IntegrationQueueResult:
        payload = attempt.get("payload") or {}
        fields = self._revert_fields(attempt)
        if payload.get("outcome") == "succeeded":
            handle.status = "failed"
            self._project_terminal_status(
                handle, "blocked", "main validation failed after checked revert",
                validation_output, observed=observed,
                declared=handle.declared_touches, revert_attempt=attempt,
            )
            self._block_dependents(handle.spec_id)
            self._revert_failure = self._scan_durable_revert_barrier()
            return IntegrationQueueResult(
                reverted=[handle.spec_id],
                decisions=[QueueDecision(
                    handle.spec_id, "reverted", str(payload["main_before"]),
                    str(payload["main_after"]), observed,
                    reason="main_validation_failed_revert_succeeded",
                    validation_output=validation_output,
                    **fields, **evidence,
                )],
            )
        self._revert_failure = {
            "spec_id": handle.spec_id,
            "run_id": self._terminal_run_id(handle),
            "reason_code": payload.get("reason_code"),
        }
        handle.status = "held"
        return IntegrationQueueResult(
            held=[handle.spec_id],
            decisions=[QueueDecision(
                handle.spec_id, "held", str(payload.get("main_before") or ""),
                str(payload.get("main_after") or self._head()), observed,
                reason=str(payload.get("reason_code") or "NS-INTEGRATION-REVERT-UNKNOWN"),
                validation_output=validation_output,
                human_status_ping_required=True,
                **fields, **evidence,
            )],
        )

    def _recover_checked_revert(
        self, handle: WorktreeHandle,
    ) -> IntegrationQueueResult | None:
        """Replay an attempt without mistaking red main for clean recovery."""
        run_id = self._terminal_run_id(handle)
        if self.status_store.get_terminal_decision(handle.spec_id, run_id) is not None:
            return None
        history = self.status_store.get_revert_attempt_history(handle.spec_id, run_id)
        if not history:
            return None
        attempt = history[-1]
        payload = attempt.get("payload") or {}
        outcome = payload.get("outcome")
        current = self._head()
        observed = list(payload.get("observed_files") or ())
        if outcome == "succeeded":
            if current != payload.get("main_after"):
                return self._classify_ambiguous_revert(handle, attempt, observed)
            return self._classify_checked_revert(
                handle, attempt, observed, "replayed durable successful revert",
                repair_result="replayed",
            )
        parent = self._git(["rev-parse", f"{current}^"])
        tree_matches_before = self._git([
            "diff", "--exit-code", str(payload.get("main_before") or ""), current,
        ])
        if (
            current != payload.get("merge_revision")
            and parent.returncode == 0
            and parent.stdout.strip() == payload.get("merge_revision")
            and tree_matches_before.returncode == 0
            and not self._main_is_dirty()
        ):
            reconciled = self.status_store.record_revert_attempt(
                handle.spec_id, run_id, payload={
                    **payload,
                    "outcome": "succeeded",
                    "reason_code": "NS-INTEGRATION-REVERT-SUCCEEDED-RECONCILED",
                    "main_after": current,
                    "returncode": 0,
                    "reconciled_from_checkpoint_id": attempt["checkpoint_id"],
                },
            )
            return self._classify_checked_revert(
                handle, reconciled, observed,
                "reconciled committed revert after interrupted outcome persistence",
                repair_result="replayed",
            )
        if current != payload.get("merge_revision") or self._main_is_dirty():
            return self._classify_ambiguous_revert(handle, attempt, observed)
        replay = self._checked_revert(
            handle, str(payload.get("main_before") or ""), current, observed,
        )
        return self._classify_checked_revert(
            handle, replay, observed, "replayed incomplete revert attempt",
            repair_result="replayed",
        )

    def _classify_ambiguous_revert(
        self, handle: WorktreeHandle, attempt: Dict[str, Any], observed: List[str],
    ) -> IntegrationQueueResult:
        payload = attempt.get("payload") or {}
        self._revert_failure = {
            "spec_id": handle.spec_id,
            "run_id": self._terminal_run_id(handle),
            "reason_code": "NS-INTEGRATION-REVERT-RECOVERY-AMBIGUOUS",
        }
        handle.status = "held"
        return IntegrationQueueResult(
            held=[handle.spec_id],
            decisions=[QueueDecision(
                handle.spec_id, "held", str(payload.get("main_before") or ""),
                self._head(), observed,
                reason="NS-INTEGRATION-REVERT-RECOVERY-AMBIGUOUS",
                human_status_ping_required=True,
                **self._revert_fields(attempt),
            )],
        )

    def _merge_validate_or_revert(self, handle: WorktreeHandle, before: str, observed: List[str], result: IntegrationQueueResult, **evidence: Any) -> bool:
        lease = self.release_surface_lease
        if lease is not None and lease.covers(observed):
            outcome = lease.acquire()
            if outcome.status == "contended":
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(
                    handle.spec_id, "held", before, before, observed,
                    reason="release_surface_lease_contention: release surface held by another integration",
                    lease_outcome="contended",
                    human_status_ping_required=True,
                    **evidence,
                ))
                return False
            try:
                evidence = {
                    **evidence,
                    "lease_outcome": outcome.status,
                    "lease_warning": outcome.warning,
                }
                return self._merge_validate_or_revert_locked(handle, before, observed, result, **evidence)
            finally:
                lease.release(outcome)
        return self._merge_validate_or_revert_locked(
            handle, before, observed, result, lease_outcome="not_required", **evidence,
        )

    @staticmethod
    def _merge_fields(attempt: Dict[str, Any]) -> Dict[str, Any]:
        payload = attempt.get("payload") or {}
        return {
            "merge_attempt_id": attempt.get("event_id"),
            "merge_outcome": payload.get("outcome", "unknown"),
            "merge_returncode": payload.get("returncode"),
            "merge_recovery_rule": payload.get("recovery_rule", "unknown"),
        }

    def _merge_application_state(
        self, main_before: str, candidate: str,
    ) -> tuple[bool, str, str]:
        """Prove either one exact merge commit or an already-contained candidate."""
        try:
            current = self._head()
            if self._main_has_external_dirty_state():
                return False, current, "main is dirty after merge command"
            ancestor = self._git(["merge-base", "--is-ancestor", candidate, current])
            if ancestor.returncode != 0:
                return False, current, "candidate is not integrated into current main"
            if current == main_before:
                contained_before = self._git([
                    "merge-base", "--is-ancestor", candidate, main_before,
                ])
                if contained_before.returncode == 0:
                    return True, current, "candidate already contained in main_before"
                return False, current, "exit-zero merge made no semantic progress"
            first = self._git(["rev-parse", f"{current}^1"])
            second = self._git(["rev-parse", f"{current}^2"])
            actual_tree = self._git(["rev-parse", f"{current}^{{tree}}"])
            expected_tree = self._git([
                "merge-tree", "--write-tree", main_before, candidate,
            ])
            expected_tree_id = expected_tree.stdout.splitlines()[0].strip() \
                if isinstance(expected_tree.stdout, str) and expected_tree.stdout else ""
            if (
                first.returncode == 0 and second.returncode == 0
                and first.stdout.strip() == main_before
                and second.stdout.strip() == candidate
                and actual_tree.returncode == 0
                and expected_tree.returncode == 0
                and actual_tree.stdout.strip() == expected_tree_id
            ):
                return True, current, "exact two-parent candidate merge and tree"
            return False, current, "merge HEAD parent/tree shape is not owned"
        except (Exception, KeyboardInterrupt) as exc:
            return False, main_before, f"merge postcondition inspection failed: {type(exc).__name__}"

    def _main_has_external_dirty_state(self) -> bool:
        """Ignore only this queue's exact untracked evidence file."""
        tracked = self._git(["diff", "--quiet"])
        staged = self._git(["diff", "--cached", "--quiet"])
        untracked = self._git(["ls-files", "--others", "--exclude-standard"])
        if tracked.returncode != 0 or staged.returncode != 0 or untracked.returncode != 0:
            return True
        allowed: str | None = None
        if self.evidence_path is not None:
            try:
                allowed = self.evidence_path.resolve().relative_to(
                    self.repo_root.resolve(),
                ).as_posix()
            except ValueError:
                allowed = None
        return any(
            path and path != allowed for path in untracked.stdout.splitlines()
        )

    def _terminalize_merge_failure(
        self, handle: WorktreeHandle, attempt: Dict[str, Any], reason_code: str,
        observed: List[str], **evidence: Any,
    ) -> IntegrationQueueResult:
        payload = attempt.get("payload") or {}
        handle.status = "failed"
        self._project_terminal_status(
            handle, "blocked", reason_code,
            observed=observed, declared=handle.declared_touches,
            merge_attempt=attempt,
        )
        self._block_dependents(handle.spec_id)
        return IntegrationQueueResult(
            reverted=[handle.spec_id],
            decisions=[QueueDecision(
                handle.spec_id, "reverted", str(payload.get("main_before") or ""),
                self._head(), observed, reason=reason_code,
                **self._merge_fields(attempt), **evidence,
            )],
        )

    def _recover_merge_failure(
        self, handle: WorktreeHandle, reserved: List[str],
    ) -> IntegrationQueueResult | None:
        """Classify durable incomplete/held merge evidence before any mutation."""
        run_id = self._terminal_run_id(handle)
        history = self.status_store.get_merge_attempt_history(handle.spec_id, run_id)
        if not history:
            return None
        attempt = history[-1]
        payload = attempt.get("payload") or {}
        outcome = payload.get("outcome")
        if outcome == "succeeded":
            valid, current, detail = self._merge_application_state(
                str(payload.get("main_before") or ""),
                str(payload.get("candidate_revision") or ""),
            )
            observed_success = payload.get("observed_files")
            if not isinstance(observed_success, list) or not all(
                isinstance(path, str) for path in observed_success
            ):
                observed_success = []
            if not valid:
                attempt = self.status_store.record_merge_attempt(
                    handle.spec_id, run_id, payload={
                        **payload, "outcome": "recovery_required",
                        "reason_code": "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED",
                        "recovery_rule": "restore_exact_main_then_retry_once",
                        "main_after": current,
                        "stderr": "\n".join(filter(None, (
                            str(payload.get("stderr") or ""), detail,
                        ))),
                        "reconciled_event_id": attempt["event_id"],
                    },
                )
                payload = attempt["payload"]
                outcome = "recovery_required"
            else:
                passed, output = self.validate_main(handle)
                if passed:
                    handle.status = "accepted"
                    self._project_terminal_status(
                        handle, "done",
                        "accepted by recovered serialized integration queue",
                        observed=observed_success, declared=handle.declared_touches,
                    )
                    cleanup = self.cleanup_terminal_resources(handle)
                    self.release(handle.spec_id)
                    return IntegrationQueueResult(
                        accepted=[handle.spec_id],
                        decisions=[QueueDecision(
                            handle.spec_id, "accepted",
                            str(payload.get("main_before") or ""), current,
                            observed_success, reason="durable_merge_success_recovered",
                            validation_output=output, reserved_surfaces=reserved,
                            cleanup_outcome=cleanup.outcome,
                            cleanup_reason_code=cleanup.reason_code,
                            cleanup_resources=cleanup.resources,
                            **self._merge_fields(attempt),
                        )],
                    )
                revert = self._checked_revert(
                    handle, str(payload.get("main_before") or ""), current,
                    observed_success,
                )
                return self._classify_checked_revert(
                    handle, revert, observed_success, output,
                    reserved_surfaces=reserved,
                )
        observed = payload.get("observed_files")
        if not isinstance(observed, list) or not all(isinstance(p, str) for p in observed):
            observed = []
        integration_ref = handle.verified_revision or handle.branch_name
        resolved = self._git([
            "rev-parse", "--verify", f"{integration_ref}^{{commit}}",
        ])
        identity_matches = (
            resolved.returncode == 0
            and resolved.stdout.strip() == payload.get("candidate_revision")
        )
        safe_main = (
            self._head() == payload.get("main_before")
            and not self._main_is_dirty()
        )
        if outcome == "started" and identity_matches:
            reconciled_outcome = "interrupted" if safe_main else "recovery_required"
            reconciled_reason = (
                "NS-INTEGRATION-MERGE-INTERRUPTED"
                if safe_main else "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED"
            )
            reconciled_rule = (
                "retry_once_on_restart"
                if safe_main else "restore_exact_main_then_retry_once"
            )
            attempt = self.status_store.record_merge_attempt(
                handle.spec_id, run_id, payload={
                    **payload, "outcome": reconciled_outcome,
                    "reason_code": reconciled_reason,
                    "recovery_rule": reconciled_rule,
                    "main_after": self._head(),
                    "started_event_id": attempt["event_id"],
                },
            )
            payload = attempt["payload"]
            outcome = reconciled_outcome
        if not identity_matches:
            reason = "NS-INTEGRATION-MERGE-RECOVERY-IDENTITY-MISMATCH"
        elif not safe_main:
            reason = "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED"
        else:
            reason = ""
        if reason:
            handle.status = "held"
            return IntegrationQueueResult(
                held=[handle.spec_id],
                decisions=[QueueDecision(
                    handle.spec_id, "held", str(payload.get("main_before") or ""),
                    self._head(), observed, reason=reason,
                    reserved_surfaces=reserved, human_status_ping_required=True,
                    **self._merge_fields(attempt),
                )],
            )
        if outcome == "command_failed":
            return self._terminalize_merge_failure(
                handle, attempt, "NS-INTEGRATION-MERGE-COMMAND-FAILED", observed,
                reserved_surfaces=reserved,
            )
        attempt_number = payload.get("attempt_number")
        if not isinstance(attempt_number, int) or isinstance(attempt_number, bool):
            handle.status = "held"
            return IntegrationQueueResult(
                held=[handle.spec_id],
                decisions=[QueueDecision(
                    handle.spec_id, "held", str(payload.get("main_before") or ""),
                    self._head(), observed,
                    reason="NS-INTEGRATION-MERGE-EVIDENCE-INVALID",
                    reserved_surfaces=reserved, human_status_ping_required=True,
                    **self._merge_fields(attempt),
                )],
            )
        if attempt_number >= 2:
            return self._terminalize_merge_failure(
                handle, attempt, "NS-INTEGRATION-MERGE-RETRY-EXHAUSTED", observed,
                reserved_surfaces=reserved,
            )
        # One exact retry is authorized only after durable evidence, immutable
        # candidate identity, and clean restoration of the original main.
        return None

    def _checked_merge(
        self, handle: WorktreeHandle, main_before: str, observed: List[str],
    ) -> Dict[str, Any]:
        run_id = self._terminal_run_id(handle)
        history = self.status_store.get_merge_attempt_history(handle.spec_id, run_id)
        attempt_number = 1 + sum(
            1 for row in history if (row.get("payload") or {}).get("outcome") == "started"
        )
        if attempt_number not in {1, 2}:
            raise StatusStoreError("merge retry budget exhausted before Git mutation")
        integration_ref = handle.verified_revision or handle.branch_name
        candidate = self._git([
            "rev-parse", "--verify", f"{integration_ref}^{{commit}}",
        ]).stdout.strip()
        common = {
            "main_before": main_before,
            "candidate_revision": candidate,
            "observed_files": sorted(set(observed)),
            "declared_surfaces": sorted(set(handle.declared_touches)),
            "attempt_number": attempt_number,
        }
        started = self.status_store.record_merge_attempt(
            handle.spec_id, run_id, payload={
                **common, "outcome": "started",
                "reason_code": "NS-INTEGRATION-MERGE-STARTED",
                "main_after": main_before, "returncode": None,
                "stdout": "", "stderr": "", "conflict_files": [],
                "recovery_rule": "inspect_main_then_retry_once",
            },
        )
        try:
            merged = (
                self.merge_runner(handle) if self.merge_runner is not None
                else self._git(["merge", "--no-ff", integration_ref])
            )
            raw_returncode = getattr(merged, "returncode", None)
            returncode_valid = (
                isinstance(raw_returncode, int)
                and not isinstance(raw_returncode, bool)
            )
            returncode = raw_returncode if returncode_valid else None
            raw_stdout = getattr(merged, "stdout", "")
            raw_stderr = getattr(merged, "stderr", "")
            stdout = raw_stdout if isinstance(raw_stdout, str) else (
                f"<invalid stdout type: {type(raw_stdout).__name__}>"
            )
            stderr = raw_stderr if isinstance(raw_stderr, str) else (
                f"<invalid stderr type: {type(raw_stderr).__name__}>"
            )
            if not returncode_valid:
                stderr = "\n".join(filter(None, (
                    stderr,
                    f"invalid merge returncode type: {type(raw_returncode).__name__}",
                )))
        except (Exception, KeyboardInterrupt) as exc:
            returncode = None
            stdout = ""
            stderr = f"{type(exc).__name__}: {exc}"
        if returncode == 0:
            valid, current, detail = self._merge_application_state(main_before, candidate)
            if valid:
                succeeded = self.status_store.record_merge_attempt(
                    handle.spec_id, run_id, payload={
                        **common, "outcome": "succeeded",
                        "reason_code": "NS-INTEGRATION-MERGE-SUCCEEDED",
                        "main_after": current, "returncode": 0,
                        "stdout": stdout, "stderr": stderr,
                        "conflict_files": [], "recovery_rule": "continue_validation",
                        "started_event_id": started["event_id"],
                        "application_proof": detail,
                    },
                )
                if self.after_merge_success is not None:
                    self.after_merge_success(handle, succeeded)
                return succeeded
            stderr = "\n".join(filter(None, (stderr, detail)))
            try:
                restored = current == main_before and not self._main_has_external_dirty_state()
            except (Exception, KeyboardInterrupt) as exc:
                restored = False
                stderr = "\n".join(filter(None, (
                    stderr,
                    f"merge recovery inspection failed: {type(exc).__name__}: {exc}",
                )))
            conflict_files = []
            outcome = "postcondition_mismatch" if restored else "recovery_required"
            reason_code = (
                "NS-INTEGRATION-MERGE-POSTCONDITION-MISMATCH"
                if restored else "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED"
            )
        else:
            try:
                conflicts = self._git(["diff", "--name-only", "--diff-filter=U"])
                conflict_files = sorted(
                    path for path in conflicts.stdout.splitlines()
                    if path and not Path(path).is_absolute()
                ) if conflicts.returncode == 0 and isinstance(conflicts.stdout, str) else []
                self._git(["merge", "--abort"], check=False)
                current = self._head()
                restored = current == main_before and not self._main_has_external_dirty_state()
            except (Exception, KeyboardInterrupt) as exc:
                conflict_files = []
                current = main_before
                restored = False
                stderr = "\n".join(filter(None, (
                    stderr, f"merge recovery inspection failed: {type(exc).__name__}: {exc}",
                )))
            if returncode is None and restored:
                outcome = "interrupted"
                reason_code = "NS-INTEGRATION-MERGE-INTERRUPTED"
            elif conflict_files and restored:
                outcome = "conflict"
                reason_code = "NS-INTEGRATION-MERGE-CONFLICT"
            elif restored:
                outcome = "command_failed"
                reason_code = "NS-INTEGRATION-MERGE-COMMAND-FAILED"
            else:
                outcome = "recovery_required"
                reason_code = "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED"
        recovery_rule = (
            "restore_exact_main_then_retry_once"
            if outcome == "recovery_required" else
            "retry_once_on_restart"
            if outcome in {"conflict", "interrupted", "postcondition_mismatch"} else
            "terminal_blocked"
        )
        if self.after_merge_failure is not None:
            self.after_merge_failure(handle, started)
        return self.status_store.record_merge_attempt(
            handle.spec_id, run_id, payload={
                **common, "outcome": outcome, "reason_code": reason_code,
                "main_after": current, "returncode": returncode,
                "stdout": stdout, "stderr": stderr,
                "conflict_files": conflict_files, "recovery_rule": recovery_rule,
                "started_event_id": started["event_id"],
            },
        )

    def _classify_merge_attempt(
        self, handle: WorktreeHandle, attempt: Dict[str, Any],
        observed: List[str], **evidence: Any,
    ) -> IntegrationQueueResult:
        payload = attempt.get("payload") or {}
        outcome = payload.get("outcome")
        if outcome == "command_failed":
            return self._terminalize_merge_failure(
                handle, attempt, "NS-INTEGRATION-MERGE-COMMAND-FAILED",
                observed, **evidence,
            )
        if outcome in {
            "conflict", "interrupted", "postcondition_mismatch",
        } and payload.get("attempt_number") == 2:
            return self._terminalize_merge_failure(
                handle, attempt, "NS-INTEGRATION-MERGE-RETRY-EXHAUSTED",
                observed, **evidence,
            )
        handle.status = "held"
        return IntegrationQueueResult(
            held=[handle.spec_id],
            decisions=[QueueDecision(
                handle.spec_id, "held", str(payload.get("main_before") or ""),
                str(payload.get("main_after") or self._head()), observed,
                reason=str(payload.get("reason_code") or "NS-INTEGRATION-MERGE-UNKNOWN"),
                human_status_ping_required=True,
                **self._merge_fields(attempt), **evidence,
            )],
        )

    def _merge_validate_or_revert_locked(self, handle: WorktreeHandle, before: str, observed: List[str], result: IntegrationQueueResult, **evidence: Any) -> bool:
        attempts = 0
        while True:
            integration_ref = handle.verified_revision or handle.branch_name
            if self.authorization_gate is not None:
                # SPEC-294 R3 (Q3/Q4): re-resolve on every loop iteration
                # against the *current* candidate ref -- a repair commit
                # landing mid-loop (Scenario 5) must be re-checked, not the
                # SHA captured on entry. ``head_drift`` is the same signal
                # the caller already threaded through ``**evidence``
                # (Q3): a validation that ran before drift was detected is
                # stale and must not honor a pending authorization.
                candidate_sha = self._git(["rev-parse", "--verify", integration_ref]).stdout.strip()
                status = self.authorization_gate(
                    handle, candidate_sha, bool(evidence.get("head_drift", False)),
                )
                if status.required and not status.authorized:
                    result.held.append(handle.spec_id)
                    result.decisions.append(QueueDecision(
                        handle.spec_id, "held", before, self._head(), observed,
                        status.reason, overlap_kind="authorization_required",
                        candidate_sha=candidate_sha,
                        **evidence,
                    ))
                    return False
            merge = self._checked_merge(handle, before, observed)
            if (merge.get("payload") or {}).get("outcome") != "succeeded":
                classified = self._classify_merge_attempt(
                    handle, merge, observed, **evidence,
                )
                result.held.extend(classified.held)
                result.reverted.extend(classified.reverted)
                result.decisions.extend(classified.decisions)
                return False
            passed, output = self.validate_main(handle)
            if passed:
                handle.status = "accepted"
                self._project_terminal_status(
                    handle, "done", "accepted by serialized integration queue",
                    observed=observed, declared=handle.declared_touches,
                )
                cleanup = self.cleanup_terminal_resources(handle)
                after = self._head()
                result.accepted.append(handle.spec_id)
                result.decisions.append(QueueDecision(
                    handle.spec_id, "accepted", before, after, observed,
                    validation_output=output,
                    cleanup_outcome=cleanup.outcome,
                    cleanup_reason_code=cleanup.reason_code,
                    cleanup_resources=cleanup.resources,
                    **evidence,
                ))
                return True

            # Validation happened on main, so retain raw output and revert the
            # merge before asking the originating worker for a bounded repair.
            merge_revision = self._head()
            attempt = self._checked_revert(handle, before, merge_revision, observed)
            if attempt["payload"]["outcome"] != "succeeded":
                classified = self._classify_checked_revert(
                    handle, attempt, observed, output, **evidence,
                )
                result.held.extend(classified.held)
                result.decisions.extend(classified.decisions)
                return False
            attempts += 1
            if (not handle.verified_revision and attempts <= self.max_repair_attempts
                    and self.request_repair and self.request_repair(handle, output)):
                rebased, rebase_outcome = self._rebase(handle)
                if not rebased:
                    result.held.append(handle.spec_id)
                    repair_evidence = {**evidence, "rebase_outcome": rebase_outcome, "repair_result": "failed"}
                    result.decisions.append(QueueDecision(handle.spec_id, "held", before, self._head(), observed, "repair rebase failed", output, **repair_evidence))
                    return False
                continue
            handle.status = "failed"
            self._project_terminal_status(
                handle, "blocked", "main validation failed after bounded repair", output,
                observed=observed, declared=handle.declared_touches,
                revert_attempt=attempt,
            )
            self._block_dependents(handle.spec_id)
            result.reverted.append(handle.spec_id)
            result.decisions.append(QueueDecision(
                handle.spec_id, "reverted", before, self._head(), observed,
                "main_validation_failed_revert_succeeded", output,
                repair_result="exhausted", **self._revert_fields(attempt), **evidence,
            ))
            return False

    def _rebase(self, handle: WorktreeHandle) -> Tuple[bool, str]:
        rebase = subprocess.run(["git", "rebase", self.main_branch], cwd=str(handle.worktree_path), capture_output=True, text=True)
        if rebase.returncode == 0:
            self._last_rebase_conflicts = []
            return True, "success"
        conflicts = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"], cwd=str(handle.worktree_path),
            capture_output=True, text=True,
        )
        self._last_rebase_conflicts = sorted(path for path in conflicts.stdout.splitlines() if path and not Path(path).is_absolute())
        subprocess.run(["git", "rebase", "--abort"], cwd=str(handle.worktree_path), capture_output=True, text=True, check=False)
        return False, "conflict"

    def _verified_revision_error(self, handle: WorktreeHandle) -> str:
        revision = handle.verified_revision
        if revision is None:
            return ""
        if not GIT_COMMIT_RE.fullmatch(revision):
            return "verified_revision_invalid"
        verified = self._git(["rev-parse", "--verify", f"{revision}^{{commit}}"])
        branch = self._git(["rev-parse", "--verify", f"{handle.branch_name}^{{commit}}"])
        if verified.returncode != 0 or verified.stdout.strip() != revision:
            return "verified_revision_unavailable"
        if branch.returncode != 0 or branch.stdout.strip() != revision:
            return "verified_revision_drift"
        return ""

    def _changed_files(self, integration_ref: str) -> List[str]:
        diff = self._git(["diff", "--name-only", f"{self.main_branch}...{integration_ref}"])
        return sorted(path for path in diff.stdout.splitlines() if path)

    @staticmethod
    def _surface_overlap(left: Set[str], right: Set[str]) -> List[str]:
        return sorted({a for a in left for b in right if _surfaces_overlap(a, b)})

    def _head(self) -> str:
        return self._git(["rev-parse", "HEAD"]).stdout.strip()

    def _main_is_dirty(self) -> bool:
        status = self._git(["status", "--porcelain"])
        return status.returncode != 0 or bool(status.stdout.strip())

    def _git(self, args: List[str], *, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(self.repo_root), capture_output=True, text=True, check=check)

    def _terminal_run_id(self, handle: WorktreeHandle) -> str:
        run_id = handle.terminal_run_id or handle.integrity_run_id
        if run_id:
            return run_id
        raise ValueError(f"terminal run identity missing for {handle.spec_id}")

    def _project_terminal_status(
        self, handle: WorktreeHandle, status: str, note: str, output: str = "",
        *, observed: Optional[Iterable[str]] = None,
        declared: Optional[Iterable[str]] = None,
        revert_attempt: Optional[Dict[str, Any]] = None,
        merge_attempt: Optional[Dict[str, Any]] = None,
        invoke_crash_hook: bool = True,
    ) -> None:
        """Persist the immutable coordinator choice before status projection."""
        if self.status_store is None:
            return
        run_id = self._terminal_run_id(handle)
        decision = self.status_store.record_terminal_decision(
            handle.spec_id, run_id, status, source="integration_queue",
            reason=note, payload={
                "validation_output": output,
                "observed_files": sorted(set(observed or ())),
                "declared_surfaces": sorted(set(declared or ())),
                "completion_evidence": handle.completion_evidence_acceptance,
                "revert_attempt": revert_attempt,
                "merge_attempt": merge_attempt,
            },
        )
        if invoke_crash_hook and self.after_terminal_decision is not None:
            self.after_terminal_decision(handle, decision)
        current = self.status_store.get_state(handle.spec_id)
        already_projected = (
            current is not None
            and current.get("status") == status
            and current.get("run_id") == run_id
            and (current.get("payload") or {}).get("terminal_decision_id")
                == decision["decision_id"]
        )
        if not already_projected:
            self.status_store.update_state(
                handle.spec_id, status, run_id=run_id, source="integration_queue",
                note=note, payload={
                    "validation_output": output,
                    "terminal_decision_id": decision["decision_id"],
                },
            )
            if invoke_crash_hook and self.after_terminal_status is not None:
                self.after_terminal_status(handle, decision)
        self.terminal_frontmatter_projector.project(handle, decision)

    def recover_terminal_projection(
        self, handle: WorktreeHandle, *, record_evidence: bool = True,
    ) -> str | None:
        """Resume a persisted choice without allowing recovery to choose anew."""
        if self.status_store is None:
            return None
        run_id = self._terminal_run_id(handle)
        decision = self.status_store.get_terminal_decision(handle.spec_id, run_id)
        if decision is None:
            return None
        payload = decision.get("payload") or {}
        observed = payload.get("observed_files")
        declared = payload.get("declared_surfaces")
        if (
            not isinstance(observed, list)
            or not all(isinstance(path, str) for path in observed)
            or not isinstance(declared, list)
            or not all(isinstance(path, str) for path in declared)
        ):
            raise ValueError("terminal decision surface evidence is missing or invalid")
        self._project_terminal_status(
            handle, decision["decision"], decision.get("reason") or "terminal recovery",
            str(payload.get("validation_output") or ""),
            observed=observed, declared=declared, invoke_crash_hook=False,
        )
        cleanup: CleanupResult | None = None
        if decision["decision"] == "done":
            self._accepted_files.update(observed)
            self._accepted_declared.update(declared)
            handle.status = "accepted"
            cleanup = self.cleanup_terminal_resources(handle)
            self.release(handle.spec_id)
        else:
            handle.status = "failed"
        if record_evidence and self.evidence_path is not None and not any(
            item.spec_id == handle.spec_id
            and item.reason == "immutable_terminal_projection_recovered"
            for item in self._session_evidence.decisions
        ):
            if decision["decision"] == "done":
                self._session_evidence.accepted.append(handle.spec_id)
                outcome = "accepted"
            else:
                self._session_evidence.reverted.append(handle.spec_id)
                outcome = "reverted"
            head = self._head()
            self._session_evidence.decisions.append(QueueDecision(
                handle.spec_id, outcome, head, head, observed,
                reason="immutable_terminal_projection_recovered",
                validation_output=str(payload.get("validation_output") or ""),
                applied_revision=handle.verified_revision or "",
                cleanup_outcome=cleanup.outcome if cleanup else "not_attempted",
                cleanup_reason_code=cleanup.reason_code if cleanup else "",
                cleanup_resources=cleanup.resources if cleanup else [],
            ))
            write_integration_queue_result(self._session_evidence, self.evidence_path)
        return str(decision["decision"])

    def restore_accepted_terminal_decision(
        self, spec_id: str, decision: Dict[str, Any],
    ) -> bool:
        """Restore pre-merge overlap memory from one selected recovered choice."""
        if not isinstance(decision, dict) or decision.get("spec_id") != spec_id:
            raise ValueError("recovered terminal decision spec identity is invalid")
        if decision.get("decision") != "done":
            raise ValueError("only a recovered done decision can seed accepted surfaces")
        run_id = decision.get("run_id")
        decision_id = decision.get("decision_id")
        if (
            not isinstance(run_id, str) or not run_id
            or isinstance(decision_id, bool) or not isinstance(decision_id, int)
            or decision_id <= 0
        ):
            raise ValueError("recovered terminal decision identity is invalid")
        payload = decision.get("payload")
        observed = payload.get("observed_files") if isinstance(payload, dict) else None
        declared = payload.get("declared_surfaces") if isinstance(payload, dict) else None
        for label, surfaces in (("observed", observed), ("declared", declared)):
            if not isinstance(surfaces, list) or not all(
                isinstance(path, str)
                and bool(path)
                and not PurePosixPath(path).is_absolute()
                and ".." not in PurePosixPath(path).parts
                for path in surfaces
            ):
                raise ValueError(f"recovered terminal {label} surfaces are invalid")
        identity = (spec_id, run_id, decision_id)
        if identity in self._restored_terminal_decisions:
            return False
        self._accepted_files.update(observed)
        self._accepted_declared.update(declared)
        self._restored_terminal_decisions.add(identity)
        return True

    def _block_dependents(self, failed_spec_id: str) -> None:
        """Persist only descendants; unrelated specs remain runnable."""
        if self.status_store is None:
            return
        blocked = {failed_spec_id}
        changed = True
        while changed:
            changed = False
            for spec_id, dependencies in self.dependency_graph.items():
                if spec_id not in blocked and blocked.intersection(dependencies):
                    blocked.add(spec_id)
                    changed = True
        for spec_id in sorted(blocked - {failed_spec_id}):
            self.status_store.update_state(
                spec_id, "blocked", source="integration_queue",
                note=f"blocked by {failed_spec_id}",
                payload={"blocking_ancestor": failed_spec_id},
            )


def write_integration_queue_result(
    result: IntegrationQueueResult,
    output_path: Path,
    *,
    operation_key: str | None = None,
    operation_digest: str | None = None,
) -> Path:
    """Persist auditable queue decisions as a machine-readable artifact."""
    result_record = {
        "phase": "terminal",
        "operation_key": operation_key,
        "operation_digest": operation_digest,
        "accepted": result.accepted,
        "held": result.held,
        "reverted": result.reverted,
        "decisions": [asdict(decision) for decision in result.decisions],
        "integrity_failures": result.integrity_failures,
    }
    _write_queue_record(output_path, result_record)
    return output_path


def write_prepared_integration_intent(
    intent: Mapping[str, Any], output_path: Path
) -> Path:
    """Fsync a closed keyed intent before the serialized queue mutates Git."""
    if intent.get("phase") != "prepared":
        raise ValueError("integration intent must be prepared")
    _write_queue_record(output_path, dict(intent))
    return output_path


def _write_queue_record(output_path: Path, operation: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    operations: Dict[str, Any] = {}
    if output_path.is_file():
        try:
            prior = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(prior.get("operations"), dict):
                operations = dict(prior["operations"])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("durable integration queue evidence is unreadable") from exc
    operation_key = operation.get("operation_key")
    if operation_key is not None:
        operations[hashlib.sha256(operation_key.encode("utf-8")).hexdigest()] = operation
    record = {**operation, "operations": operations}
    body = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        directory = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_keyed_queue_record(
    output_path: Path, operation_key: str, operation_digest: str | None
) -> Dict[str, Any] | None:
    if not output_path.is_file():
        return None
    try:
        record = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("durable integration queue evidence is unreadable") from exc
    operations = record.get("operations")
    operation = None
    if isinstance(operations, dict):
        operation = operations.get(
            hashlib.sha256(operation_key.encode("utf-8")).hexdigest()
        )
    if operation is None and record.get("operation_key") == operation_key:
        operation = record
    if not isinstance(operation, dict):
        return None
    if operation.get("operation_key") != operation_key:
        raise ValueError("durable integration queue identity collision")
    if operation.get("operation_digest") != operation_digest:
        raise ValueError("divergent integration queue operation reuse")
    return operation


def integration_metrics_summary(result: IntegrationQueueResult) -> Dict[str, Any]:
    """Return redacted aggregate integration metrics with explicit N/A rates.

    Queue evidence deliberately contains spec IDs and repository-relative paths
    only.  This summary keeps reports safe to aggregate across projects.
    """
    decisions = result.decisions
    denominator = len(decisions)

    def rate(count: int) -> Any:
        return "N/A" if denominator == 0 else count / denominator

    conflicts = sum(item.rebase_outcome == "conflict" for item in decisions)
    automatic = sum(item.outcome == "accepted" and item.rebase_outcome == "success" for item in decisions)
    return {
        "integrations": denominator,
        "queue_wait_s_total": sum(item.queue_wait_s for item in decisions),
        "head_drift_count": sum(item.head_drift for item in decisions),
        "conflict_count": conflicts,
        "conflict_rate": rate(conflicts),
        "automatic_resolution_count": automatic,
        "automatic_resolution_rate": rate(automatic),
        "human_status_ping_required": sum(item.human_status_ping_required for item in decisions),
    }


# ---------------------------------------------------------------------------
# Planning (pure, no I/O)
# ---------------------------------------------------------------------------

def plan_parallel_execution(
    graph: Dict[str, Set[str]],
    execution_order: List[str],
) -> List[ParallelLayer]:
    """
    Compute parallel layers from a dependency graph and execution order.

    Pure function — no I/O. Specs not in execution_order (e.g. blocked/cycle
    specs) are automatically excluded.

    Args:
        graph: Dict mapping spec_id -> set of its dependency spec_ids.
        execution_order: List of spec_ids eligible for execution.

    Returns:
        List of ParallelLayer sorted by layer_index.
    """
    if not execution_order:
        return []

    order_set = set(execution_order)

    # Compute topological depth for each spec
    depth: Dict[str, int] = {}
    for spec_id in execution_order:
        deps = graph.get(spec_id, set()) & order_set
        if not deps:
            depth[spec_id] = 0
        else:
            depth[spec_id] = max(depth[d] for d in deps) + 1

    # Group by depth
    depth_groups: Dict[int, List[str]] = {}
    for spec_id, d in depth.items():
        depth_groups.setdefault(d, []).append(spec_id)

    # Build layers sorted by depth, each group sorted alphabetically
    layers: List[ParallelLayer] = []
    for layer_idx in sorted(depth_groups.keys()):
        spec_ids = sorted(depth_groups[layer_idx])
        preceding = list(range(layer_idx))
        layers.append(
            ParallelLayer(
                layer_index=layer_idx,
                spec_ids=spec_ids,
                is_parallel=len(spec_ids) > 1,
                dependencies_satisfied_by=preceding,
            )
        )

    return layers


_TERMINAL_BLOCKING_STATUSES = frozenset({"blocked", "failed"})
_COARSE_TOUCHES = frozenset({"", ".", "/", "*", "**"})


def _surfaces_overlap(left: str, right: str) -> bool:
    """Return whether two declared path/capability surfaces can collide."""
    left = left.strip().rstrip("/")
    right = right.strip().rstrip("/")
    if not left or not right:
        return True
    if left == right:
        return True
    if left.startswith("capability:") or right.startswith("capability:"):
        return False
    return left.startswith(right + "/") or right.startswith(left + "/")


def _is_coarse_touches(touches: Tuple[str, ...]) -> bool:
    return not touches or any(surface.strip() in _COARSE_TOUCHES for surface in touches)


def _conflicts_with(
    candidate: AdmissionSpec,
    other: AdmissionSpec,
    missing_touches_policy: str,
) -> List[str]:
    """Return the declared surfaces that prevent two specs running together."""
    if _is_coarse_touches(candidate.touches) or _is_coarse_touches(other.touches):
        if missing_touches_policy == "exclusive":
            return ["missing_or_coarse_touches"]
        return []
    return sorted({
        f"{left} <-> {right}"
        for left in candidate.touches
        for right in other.touches
        if _surfaces_overlap(left, right)
    })


def plan_dynamic_admission(
    specs: Iterable[AdmissionSpec],
    worker_limit: int,
    *,
    active_specs: Iterable[AdmissionSpec] = (),
    missing_touches_policy: str = "exclusive",
    dependency_statuses: Mapping[str, str] | None = None,
    dependency_errors: Mapping[str, str] | None = None,
    dependency_details: Mapping[str, str] | None = None,
) -> AdmissionPlan:
    """Build a pure, deterministic admission plan for the current DAG frontier.

    Only ready specs can enter the frontier. A blocked or failed dependency blocks
    its transitive descendants while unrelated specs stay independently eligible.
    Invalid dependencies and cycles are never runnable. ``exclusive`` is the
    conservative policy for missing or coarse ``touches:`` declarations.
    """
    if worker_limit < 0:
        raise ValueError("worker_limit must be non-negative")
    if missing_touches_policy not in {"exclusive", "allow"}:
        raise ValueError("missing_touches_policy must be 'exclusive' or 'allow'")

    spec_by_id = {spec.spec_id: spec for spec in specs}
    external_statuses = {
        str(spec_id): str(status).lower()
        for spec_id, status in (dependency_statuses or {}).items()
    }
    resolution_errors = dict(dependency_errors or {})
    resolved_details = dict(dependency_details or {})
    active_by_id = {spec.spec_id: spec for spec in active_specs}
    active_by_id.update({
        spec.spec_id: spec
        for spec in spec_by_id.values()
        if spec.status == "in_progress"
    })

    graph = {spec_id: set(spec.after) for spec_id, spec in spec_by_id.items()}
    invalid = {
        spec_id
        for spec_id, dependencies in graph.items()
        if any(
            dependency in resolution_errors
            or (dependency not in spec_by_id and dependency not in external_statuses)
            for dependency in dependencies
        )
    }
    cycle_members = {
        spec_id
        for cycle in _find_cycles(graph)
        for spec_id in cycle
    }
    non_runnable = invalid | cycle_members
    changed = True
    while changed:
        changed = False
        for spec_id, dependencies in graph.items():
            if spec_id not in non_runnable and dependencies & non_runnable:
                non_runnable.add(spec_id)
                changed = True

    blocked_cache: Dict[str, Optional[str]] = {}

    def blocking_ancestor(spec_id: str, seen: Set[str]) -> Optional[str]:
        if spec_id in blocked_cache:
            return blocked_cache[spec_id]
        spec = spec_by_id[spec_id]
        if spec.status in _TERMINAL_BLOCKING_STATUSES:
            blocked_cache[spec_id] = spec_id
            return spec_id
        if spec_id in seen:
            return None
        for dependency in sorted(spec.after):
            if dependency in spec_by_id:
                ancestor = blocking_ancestor(dependency, seen | {spec_id})
                if ancestor:
                    blocked_cache[spec_id] = ancestor
                    return ancestor
            elif external_statuses.get(dependency) in _TERMINAL_BLOCKING_STATUSES:
                blocked_cache[spec_id] = dependency
                return dependency
        blocked_cache[spec_id] = None
        return None

    decisions: Dict[str, AdmissionDecision] = {}
    frontier: List[AdmissionSpec] = []
    for spec in sorted(spec_by_id.values(), key=lambda item: (item.priority, item.spec_id)):
        if spec.spec_id in active_by_id:
            decisions[spec.spec_id] = AdmissionDecision(
                spec.spec_id, "not_ready", "already_active", "already occupies a worker slot"
            )
        elif spec.spec_id in invalid:
            failures = [resolution_errors[dep] for dep in spec.after if dep in resolution_errors]
            decisions[spec.spec_id] = AdmissionDecision(
                spec.spec_id,
                "invalid",
                "dependency_resolution_failed" if failures else "invalid_dependency",
                "; ".join(failures) if failures else "references a missing dependency",
            )
        elif spec.spec_id in cycle_members:
            decisions[spec.spec_id] = AdmissionDecision(
                spec.spec_id, "invalid", "dependency_cycle", "belongs to a dependency cycle"
            )
        elif spec.spec_id in non_runnable:
            decisions[spec.spec_id] = AdmissionDecision(
                spec.spec_id, "invalid", "invalid_dependency_graph", "depends on an invalid dependency graph"
            )
        else:
            ancestor = blocking_ancestor(spec.spec_id, set())
            if ancestor:
                decisions[spec.spec_id] = AdmissionDecision(
                    spec.spec_id,
                    "blocked",
                    "blocked_dependency",
                    f"blocked by dependency {ancestor}",
                    blocking_ancestor=ancestor,
                )
            elif spec.status != "ready":
                decisions[spec.spec_id] = AdmissionDecision(
                    spec.spec_id, "not_ready", "status_not_ready", f"status is {spec.status}"
                )
            elif all(
                (spec_by_id[dependency].status if dependency in spec_by_id else external_statuses.get(dependency)) == "done"
                for dependency in spec.after
            ):
                frontier.append(spec)
            else:
                pending_dependencies = [
                    dependency
                    for dependency in spec.after
                    if (spec_by_id[dependency].status if dependency in spec_by_id else external_statuses.get(dependency)) != "done"
                ]
                decisions[spec.spec_id] = AdmissionDecision(
                    spec.spec_id,
                    "not_ready",
                    "dependencies_pending",
                    "; ".join(resolved_details.get(dependency, f"waiting for dependency {dependency}")
                              for dependency in pending_dependencies),
                )

    admitted: List[AdmissionSpec] = []
    slots = max(0, worker_limit - len(active_by_id))
    active = list(active_by_id.values())
    for candidate in frontier:
        conflicts = []
        for other in active + admitted:
            surfaces = _conflicts_with(candidate, other, missing_touches_policy)
            if surfaces:
                conflicts.append((other.spec_id, surfaces))
        if conflicts:
            decisions[candidate.spec_id] = AdmissionDecision(
                candidate.spec_id,
                "deferred",
                "surface_overlap",
                "declared surfaces overlap an active or admitted spec",
                conflicting_spec_ids=[spec_id for spec_id, _ in conflicts],
                conflicting_surfaces=sorted({surface for _, surfaces in conflicts for surface in surfaces}),
            )
        elif len(admitted) >= slots:
            decisions[candidate.spec_id] = AdmissionDecision(
                candidate.spec_id, "deferred", "concurrency_limit", "no worker capacity remains"
            )
        else:
            admitted.append(candidate)
            decisions[candidate.spec_id] = AdmissionDecision(
                candidate.spec_id, "admitted", "compatible", "dependencies complete and surface is compatible"
            )

    ordered = [decisions[spec_id] for spec_id in sorted(decisions)]
    return AdmissionPlan(
        worker_limit=worker_limit,
        active_spec_ids=sorted(active_by_id),
        missing_touches_policy=missing_touches_policy,
        frontier=[spec.spec_id for spec in frontier],
        admitted=[spec.spec_id for spec in admitted],
        decisions=ordered,
    )


def write_admission_plan(plan: AdmissionPlan, output_dir: Path) -> Tuple[Path, Path]:
    """Persist separate machine and reviewer-readable artifacts for a plan."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "admission-plan.json"
    markdown_path = output_dir / "admission-plan.md"
    json_path.write_text(json.dumps(plan.to_dict(), indent=2) + "\n")
    markdown_path.write_text(plan.to_human_readable())
    return json_path, markdown_path


def _find_cycles(graph: Dict[str, Set[str]]) -> List[Set[str]]:
    """Find cycle members without importing the CLI DAG module."""
    cycles: List[Set[str]] = []
    stack: List[str] = []
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(spec_id: str) -> None:
        if spec_id in visiting:
            cycles.append(set(stack[stack.index(spec_id):]))
            return
        if spec_id in visited:
            return
        visiting.add(spec_id)
        stack.append(spec_id)
        for dependency in sorted(graph.get(spec_id, set())):
            if dependency in graph:
                visit(dependency)
        stack.pop()
        visiting.remove(spec_id)
        visited.add(spec_id)

    for spec_id in sorted(graph):
        visit(spec_id)
    return cycles


# ---------------------------------------------------------------------------
# Fan-out (path computation + worktree creation)
# ---------------------------------------------------------------------------

def fan_out(
    layer: ParallelLayer,
    repo_root: Path,
    branch_prefix: str = "nightshift",
) -> List[WorktreeHandle]:
    """
    Compute worktree paths for a parallel layer. Does NOT create worktrees.

    Args:
        layer: The ParallelLayer to fan out.
        repo_root: Root of the git repository.
        branch_prefix: Prefix for branch names.

    Returns:
        List of WorktreeHandle sorted by spec_id, all with status="pending".
    """
    handles: List[WorktreeHandle] = []
    for spec_id in sorted(layer.spec_ids):
        worktree_path = worktree_path_for_spec(repo_root, spec_id)
        branch_name = f"{branch_prefix}/{spec_id}"
        events_dir = worktree_path / ".nightshift" / "runs" / spec_id / "events"
        checkpoint_dir = worktree_path / ".nightshift" / "runs" / spec_id / "checkpoints"

        handles.append(
            WorktreeHandle(
                spec_id=spec_id,
                worktree_path=worktree_path,
                branch_name=branch_name,
                events_dir=events_dir,
                checkpoint_dir=checkpoint_dir,
                status="pending",
            )
        )
    return handles


def prepare_worktrees(
    handles: List[WorktreeHandle],
    repo_root: Path,
) -> List[WorktreeHandle]:
    """
    Create actual git worktrees for each handle.

    Existing worktrees or branches are retained for the durable cleanup owner;
    preparation never performs destructive best-effort cleanup. On failure for
    any handle, sets status="failed" and continues.

    Args:
        handles: List of WorktreeHandle from fan_out().
        repo_root: Root of the git repository.

    Returns:
        Updated handles with status reflecting creation outcome.
    """
    for handle in handles:
        try:
            wt_path_str = str(handle.worktree_path)
            assert_managed_worktree_path(repo_root, handle.worktree_path)
            if handle.worktree_path.exists():
                assert_worktree_owner(repo_root, handle.worktree_path)
                handle.status = "failed"
                continue
            existing_branch = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{handle.branch_name}"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if existing_branch.returncode == 0:
                handle.status = "failed"
                continue

            # Create worktree with new branch
            result = subprocess.run(
                ["git", "worktree", "add", wt_path_str, "-b", handle.branch_name],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                handle.status = "failed"
                continue
            assert_worktree_owner(repo_root, handle.worktree_path)

            # Create events and checkpoint directories
            handle.events_dir.mkdir(parents=True, exist_ok=True)
            handle.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        except (OSError, subprocess.SubprocessError, WorktreePathError):
            handle.status = "failed"

    return handles


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def detect_conflicts(
    handles: List[WorktreeHandle],
) -> List[Tuple[str, str, List[str]]]:
    """
    Detect file-level conflicts between completed worktree handles.

    Only considers handles with status=="completed". For each pair,
    compares files_changed lists for overlaps.

    Args:
        handles: List of WorktreeHandle.

    Returns:
        List of (spec_id_a, spec_id_b, [overlapping_files]) tuples.
        Empty list means no conflicts.
    """
    completed = [h for h in handles if h.status == "completed"]
    conflicts: List[Tuple[str, str, List[str]]] = []

    for i in range(len(completed)):
        for j in range(i + 1, len(completed)):
            a = completed[i]
            b = completed[j]
            overlap = sorted(set(a.files_changed) & set(b.files_changed))
            if overlap:
                # Ensure deterministic ordering (alphabetical by spec_id)
                id_a, id_b = sorted([a.spec_id, b.spec_id])
                conflicts.append((id_a, id_b, overlap))

    return conflicts


# ---------------------------------------------------------------------------
# Fan-in (merge)
# ---------------------------------------------------------------------------

def fan_in(
    handles: List[WorktreeHandle],
    repo_root: Path,
    strategy: MergeStrategy,
) -> MergeResult:
    """
    Merge completed worktree branches back into the current branch.

    Args:
        handles: List of WorktreeHandle (typically from one layer).
        repo_root: Root of the git repository.
        strategy: The merge strategy to use.

    Returns:
        MergeResult describing what was merged, conflicted, or left pending.
    """
    completed = [h for h in handles if h.status == "completed"]
    non_completed = [h for h in handles if h.status != "completed"]

    # Check for conflicts first
    file_conflicts = detect_conflicts(handles)

    if strategy == MergeStrategy.ABORT_ON_CONFLICT:
        if file_conflicts:
            return MergeResult(
                status="conflict",
                conflicted=[h.spec_id for h in completed],
                pending=[h.spec_id for h in non_completed],
                conflicts_detail=file_conflicts,
                merge_order=[],
            )

    # Sort alphabetically for deterministic merge order
    merge_candidates = sorted(completed, key=lambda h: h.spec_id)
    for handle in merge_candidates:
        try:
            _assert_handle_ownership_if_present(handle, repo_root)
        except WorktreePathError as exc:
            return MergeResult(
                status="failed",
                merged=[],
                conflicted=[],
                pending=[h.spec_id for h in handles],
                conflicts_detail=file_conflicts,
                merge_order=[],
                error=str(exc),
            )
    merge_order = [h.spec_id for h in merge_candidates]

    merged: List[str] = []
    conflicted: List[str] = []
    pending_specs: List[str] = [h.spec_id for h in non_completed]
    error_msg: Optional[str] = None

    if strategy == MergeStrategy.SEQUENTIAL_MERGE:
        for handle in merge_candidates:
            result = subprocess.run(
                ["git", "merge", "--no-ff", handle.branch_name],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                merged.append(handle.spec_id)
            else:
                conflicted.append(handle.spec_id)
                error_msg = result.stderr.strip() or result.stdout.strip()
                # Abort the failed merge
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=str(repo_root),
                    capture_output=True,
                    check=False,
                )
                # Remaining are pending
                remaining_idx = merge_candidates.index(handle) + 1
                pending_specs.extend(
                    h.spec_id for h in merge_candidates[remaining_idx:]
                )
                break

    elif strategy == MergeStrategy.REBASE_MERGE:
        for i, handle in enumerate(merge_candidates):
            if i == 0:
                # First: straight merge
                result = subprocess.run(
                    ["git", "merge", "--no-ff", handle.branch_name],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                )
            else:
                # Rebase onto updated main first
                rebase_result = subprocess.run(
                    ["git", "rebase", "HEAD", handle.branch_name],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                )
                if rebase_result.returncode != 0:
                    subprocess.run(
                        ["git", "rebase", "--abort"],
                        cwd=str(repo_root),
                        capture_output=True,
                        check=False,
                    )
                    conflicted.append(handle.spec_id)
                    error_msg = rebase_result.stderr.strip()
                    remaining_idx = i + 1
                    pending_specs.extend(
                        h.spec_id for h in merge_candidates[remaining_idx:]
                    )
                    break
                # Now merge the rebased branch
                result = subprocess.run(
                    ["git", "merge", "--no-ff", handle.branch_name],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                )

            if result.returncode == 0:
                merged.append(handle.spec_id)
            else:
                conflicted.append(handle.spec_id)
                error_msg = result.stderr.strip() or result.stdout.strip()
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=str(repo_root),
                    capture_output=True,
                    check=False,
                )
                remaining_idx = i + 1
                pending_specs.extend(
                    h.spec_id for h in merge_candidates[remaining_idx:]
                )
                break

    # Determine overall status
    if conflicted:
        status = "partial" if merged else "conflict"
    elif not merged:
        status = "failed"
    else:
        status = "success"

    return MergeResult(
        status=status,
        merged=merged,
        conflicted=conflicted,
        pending=pending_specs,
        conflicts_detail=file_conflicts,
        merge_order=merge_order,
        error=error_msg,
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_worktrees(
    handles: List[WorktreeHandle],
    repo_root: Path,
    force: bool = False,
    *,
    status_store: StatusStore | None = None,
    cleanup_protocol: CheckedCleanupProtocol | None = None,
) -> List[str]:
    """
    Clean up terminal worktrees through the durable parent-owned protocol.

    Default: cleans completed+pending, leaves failed+conflict.
    force=True: considers all. Missing durable ownership retains resources.

    Args:
        handles: List of WorktreeHandle.
        repo_root: Root of the git repository.
        force: If True, clean all regardless of status.

    Returns:
        List of cleaned spec_ids.
    """
    cleaned: List[str] = []
    keep_statuses = {"failed", "conflict"}
    if cleanup_protocol is None:
        if not isinstance(status_store, StatusStore):
            return cleaned
        cleanup_protocol = CheckedCleanupProtocol(Path(repo_root), status_store)

    for handle in handles:
        if not force and handle.status in keep_statuses:
            continue

        try:
            outcome = cleanup_protocol.cleanup(handle)
        except (OSError, subprocess.SubprocessError, WorktreePathError,
                StatusStoreError, ValueError):
            continue
        if outcome.outcome == "released":
            cleaned.append(handle.spec_id)

    return cleaned


def worktree_path_for_spec(repo_root: Path, spec_id: str) -> Path:
    """Compatibility seam for tests and callers computing a worktree handle."""
    return worktree_path(repo_root, spec_id)


def _assert_handle_ownership_if_present(handle: WorktreeHandle, repo_root: Path) -> None:
    assert_managed_worktree_path(repo_root, handle.worktree_path)
    if handle.worktree_path.exists():
        assert_worktree_owner(repo_root, handle.worktree_path)
