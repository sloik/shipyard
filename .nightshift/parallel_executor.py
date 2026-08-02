#!/usr/bin/env python3
"""
Parallel Execution Primitives for Nightshift Kit.

Provides planning, fan-out, fan-in, and worktree lifecycle management
for parallel spec execution with git worktree-based isolation.
"""

import enum
import json
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import yaml

from dependency_registry import DependencyRegistryResolver

from worktree_paths import (
    WorktreePathError,
    assert_managed_worktree_path,
    assert_worktree_owner,
    worktree_path,
)


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
        self.run_id = uuid.uuid4().hex
        self.active: Dict[str, DispatchedWorker] = {}
        self._dependency_resolver = DependencyRegistryResolver(self.specs_dir)
        self._dependency_statuses: Dict[str, str] = {}
        self._dependency_errors: Dict[str, str] = {}

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
        )
        launched: List[DispatchedWorker] = []
        by_id = {spec.spec_id: spec for spec in specs}
        for spec_id in plan.admitted:
            if spec_id in self.active:
                continue
            launched.append(self._launch(by_id[spec_id]))
        return launched

    def _load_specs(self) -> List[AdmissionSpec]:
        specs: List[AdmissionSpec] = []
        for path in sorted(self.specs_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            if not content.startswith("---"):
                continue
            parts = content.split("---", 2)
            if len(parts) < 3:
                continue
            data = yaml.safe_load(parts[1]) or {}
            spec_id = data.get("id")
            if not isinstance(spec_id, str):
                continue
            checkpoint = self.status_store.get_state(spec_id)
            status = (checkpoint or {}).get("status", data.get("status", "draft"))
            specs.append(AdmissionSpec(
                spec_id=spec_id,
                status=status,
                after=tuple(data.get("after") or ()),
                touches=tuple(data.get("touches") or ()),
                priority=int(data.get("priority", 1)),
            ))
        local_specs = {
            spec.spec_id: {"id": spec.spec_id, "status": spec.status}
            for spec in specs
        }
        resolution = self._dependency_resolver.resolve(
            (dependency for spec in specs for dependency in spec.after),
            local_specs=local_specs,
        )
        self._dependency_statuses = {
            spec_id: record.status
            for spec_id, record in resolution.resolved.items()
            if spec_id not in local_specs
        }
        self._dependency_errors = dict(resolution.errors)
        return specs

    def _admission_spec_for_active(self, worker: DispatchedWorker) -> AdmissionSpec:
        for spec in self._load_specs():
            if spec.spec_id == worker.spec_id:
                return AdmissionSpec(spec.spec_id, "in_progress", spec.after, spec.touches, spec.priority)
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
            self.status_store.update_state(
                spec_id,
                "done" if success else "pending",
                run_id=dispatched.run_id,
                source="coordinator",
                note="worker completed" if success else "worker crashed; recoverable",
                payload=outcome if isinstance(outcome, dict) else {"outcome": str(outcome)},
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


@dataclass
class IntegrationQueueResult:
    """Result of serialized fan-in with per-candidate main evidence."""

    accepted: List[str] = field(default_factory=list)
    held: List[str] = field(default_factory=list)
    reverted: List[str] = field(default_factory=list)
    decisions: List[QueueDecision] = field(default_factory=list)


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
        status_store: Any = None,
        dependency_graph: Optional[Dict[str, Set[str]]] = None,
        max_repair_attempts: int = 1,
        evidence_path: Optional[Path] = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.main_branch = main_branch
        self.validate_main = validate_main or (lambda _handle: (True, "validation not configured"))
        self.request_repair = request_repair
        self.status_store = status_store
        self.dependency_graph = dependency_graph or {}
        self.max_repair_attempts = max(0, max_repair_attempts)
        self.evidence_path = Path(evidence_path) if evidence_path else None

    def integrate(self, handles: Iterable[WorktreeHandle]) -> IntegrationQueueResult:
        """Integrate compatible completed handles in deterministic spec-ID order."""
        result = IntegrationQueueResult()
        accepted_files: Set[str] = set()
        accepted_declared: Set[str] = set()
        for handle in sorted((h for h in handles if h.status == "completed"), key=lambda h: h.spec_id):
            before = self._head()
            try:
                _assert_handle_ownership_if_present(handle, self.repo_root)
            except WorktreePathError as exc:
                result.held.append(handle.spec_id)
                result.decisions.append(
                    QueueDecision(handle.spec_id, "held", before, before, reason=str(exc))
                )
                continue
            observed = self._changed_files(handle.branch_name)
            declared = set(handle.declared_touches)
            overlap = sorted(accepted_files & set(observed))
            declared_overlap = self._surface_overlap(declared, accepted_declared)
            if overlap or declared_overlap:
                reason = "actual changed-file overlap: " + ", ".join(overlap or declared_overlap)
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(handle.spec_id, "held", before, before, observed, reason))
                continue

            if not self._rebase(handle):
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(handle.spec_id, "held", before, self._head(), observed, "reconciliation failed"))
                continue

            accepted = self._merge_validate_or_revert(handle, before, observed, result)
            if accepted:
                accepted_files.update(observed)
                accepted_declared.update(declared)
        if self.evidence_path is not None:
            write_integration_queue_result(result, self.evidence_path)
        return result

    def _merge_validate_or_revert(self, handle: WorktreeHandle, before: str, observed: List[str], result: IntegrationQueueResult) -> bool:
        attempts = 0
        while True:
            merge = self._git(["merge", "--no-ff", handle.branch_name])
            if merge.returncode != 0:
                self._git(["merge", "--abort"], check=False)
                result.held.append(handle.spec_id)
                result.decisions.append(QueueDecision(handle.spec_id, "held", before, self._head(), observed, merge.stderr.strip() or merge.stdout.strip() or "merge failed"))
                return False
            passed, output = self.validate_main(handle)
            if passed:
                handle.status = "accepted"
                self._set_status(handle.spec_id, "done", "accepted by serialized integration queue")
                _cleanup_single_worktree(handle, self.repo_root)
                after = self._head()
                result.accepted.append(handle.spec_id)
                result.decisions.append(QueueDecision(handle.spec_id, "accepted", before, after, observed, validation_output=output))
                return True

            # Validation happened on main, so retain raw output and revert the
            # merge before asking the originating worker for a bounded repair.
            self._git(["revert", "-m", "1", "HEAD", "--no-edit"])
            attempts += 1
            if attempts <= self.max_repair_attempts and self.request_repair and self.request_repair(handle, output):
                if not self._rebase(handle):
                    result.held.append(handle.spec_id)
                    result.decisions.append(QueueDecision(handle.spec_id, "held", before, self._head(), observed, "repair rebase failed", output))
                    return False
                continue
            handle.status = "failed"
            self._set_status(handle.spec_id, "blocked", "main validation failed after bounded repair", output)
            self._block_dependents(handle.spec_id)
            result.reverted.append(handle.spec_id)
            result.decisions.append(QueueDecision(handle.spec_id, "reverted", before, self._head(), observed, "main validation failed", output))
            return False

    def _rebase(self, handle: WorktreeHandle) -> bool:
        rebase = subprocess.run(["git", "rebase", self.main_branch], cwd=str(handle.worktree_path), capture_output=True, text=True)
        if rebase.returncode == 0:
            return True
        subprocess.run(["git", "rebase", "--abort"], cwd=str(handle.worktree_path), capture_output=True, text=True, check=False)
        return False

    def _changed_files(self, branch_name: str) -> List[str]:
        diff = self._git(["diff", "--name-only", f"{self.main_branch}...{branch_name}"])
        return sorted(path for path in diff.stdout.splitlines() if path)

    @staticmethod
    def _surface_overlap(left: Set[str], right: Set[str]) -> List[str]:
        return sorted({a for a in left for b in right if _surfaces_overlap(a, b)})

    def _head(self) -> str:
        return self._git(["rev-parse", "HEAD"]).stdout.strip()

    def _git(self, args: List[str], *, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(self.repo_root), capture_output=True, text=True, check=check)

    def _set_status(self, spec_id: str, status: str, note: str, output: str = "") -> None:
        if self.status_store is not None:
            self.status_store.update_state(spec_id, status, source="integration_queue", note=note, payload={"validation_output": output})

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
            self._set_status(spec_id, "blocked", f"blocked by {failed_spec_id}")


def write_integration_queue_result(result: IntegrationQueueResult, output_path: Path) -> Path:
    """Persist auditable queue decisions as a machine-readable artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "accepted": result.accepted,
        "held": result.held,
        "reverted": result.reverted,
        "decisions": [asdict(decision) for decision in result.decisions],
    }, indent=2) + "\n", encoding="utf-8")
    return output_path


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
                decisions[spec.spec_id] = AdmissionDecision(
                    spec.spec_id, "not_ready", "dependencies_pending", "waiting for dependencies"
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

    If worktree or branch already exists, removes them first.
    On failure for any handle, sets status="failed" and continues.

    Args:
        handles: List of WorktreeHandle from fan_out().
        repo_root: Root of the git repository.

    Returns:
        Updated handles with status reflecting creation outcome.
    """
    for handle in handles:
        try:
            # Clean up existing worktree if present
            wt_path_str = str(handle.worktree_path)
            assert_managed_worktree_path(repo_root, handle.worktree_path)
            if handle.worktree_path.exists():
                assert_worktree_owner(repo_root, handle.worktree_path)
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt_path_str],
                    cwd=str(repo_root),
                    capture_output=True,
                    check=False,
                )

            # Clean up existing branch if present
            subprocess.run(
                ["git", "branch", "-D", handle.branch_name],
                cwd=str(repo_root),
                capture_output=True,
                check=False,
            )

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
                # Clean up worktree for merged spec
                _cleanup_single_worktree(handle, repo_root)
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
                _cleanup_single_worktree(handle, repo_root)
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


def _cleanup_single_worktree(handle: WorktreeHandle, repo_root: Path) -> bool:
    """Remove a single worktree and its branch. Returns True on success."""
    try:
        wt_path_str = str(handle.worktree_path)
        assert_managed_worktree_path(repo_root, handle.worktree_path)
        if handle.worktree_path.exists():
            assert_worktree_owner(repo_root, handle.worktree_path)
        subprocess.run(
            ["git", "worktree", "remove", "--force", wt_path_str],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "branch", "-D", handle.branch_name],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        return True
    except (OSError, subprocess.SubprocessError, WorktreePathError):
        return False


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_worktrees(
    handles: List[WorktreeHandle],
    repo_root: Path,
    force: bool = False,
) -> List[str]:
    """
    Clean up worktrees after execution.

    Default: cleans completed+pending, leaves failed+conflict.
    force=True: cleans all. Tolerates missing worktrees.

    Args:
        handles: List of WorktreeHandle.
        repo_root: Root of the git repository.
        force: If True, clean all regardless of status.

    Returns:
        List of cleaned spec_ids.
    """
    cleaned: List[str] = []
    keep_statuses = {"failed", "conflict"}

    for handle in handles:
        if not force and handle.status in keep_statuses:
            continue

        if _cleanup_single_worktree(handle, repo_root):
            cleaned.append(handle.spec_id)

    return cleaned


def worktree_path_for_spec(repo_root: Path, spec_id: str) -> Path:
    """Compatibility seam for tests and callers computing a worktree handle."""
    return worktree_path(repo_root, spec_id)


def _assert_handle_ownership_if_present(handle: WorktreeHandle, repo_root: Path) -> None:
    assert_managed_worktree_path(repo_root, handle.worktree_path)
    if handle.worktree_path.exists():
        assert_worktree_owner(repo_root, handle.worktree_path)
