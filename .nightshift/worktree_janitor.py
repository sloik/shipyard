#!/usr/bin/env python3
"""Mechanical worktree janitor for Nightshift run isolation."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from parallel_executor import WorktreeHandle, cleanup_worktrees

try:
    from status_store import StatusStore
except ImportError:  # pragma: no cover - copied kit fallback
    StatusStore = None  # type: ignore[assignment]


KEEP_MARKER = ".nightshift-keep"
GC_STATUSES = {"done", "blocked", "failed"}
HEARTBEAT_PREFIX = "orchestrator-progress-"
WIP_MAX_AGE_DAYS = 30
PINNED_STATUSES = {"blocked", "failed"}
CONCURRENT_PATHS = {"orchestrator", "parallel", "parallel-layers", "multi-model"}
# Spec-ID tokens: uppercase alphanumeric segments, ID ends at its last all-digit
# segment; a lowercase segment (slug suffix like "-janitor") ends the ID.
_ID_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9]*$|\d+$")


@dataclass(frozen=True)
class WorktreeRecord:
    path: Path
    branch: str
    head: str = ""


@dataclass(frozen=True)
class JanitorDecision:
    spec_id: str | None
    worktree_path: Path
    branch_name: str
    status: str | None
    action: str
    reason: str


def parse_worktree_list_porcelain(output: str) -> list[WorktreeRecord]:
    records: list[WorktreeRecord] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            if "worktree" in current:
                records.append(_record_from_porcelain(current))
            current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"worktree", "branch", "HEAD"}:
            current[key] = value
    if "worktree" in current:
        records.append(_record_from_porcelain(current))
    return records


def resolve_worktree_mode(config: dict[str, Any], execution_path: str) -> str:
    """Resolve git.worktrees for a concrete Nightshift execution path."""
    raw = str((config.get("git") or {}).get("worktrees", "auto")).lower()
    if raw == "enabled":
        return "mandatory"
    if raw == "disabled":
        return "disabled"
    if raw != "auto":
        raise ValueError(f"invalid git.worktrees value: {raw!r}")
    return "mandatory" if execution_path in CONCURRENT_PATHS else "optional"


def is_unmerged(branch_name: str, repo_root: Path, main_branch: str) -> bool:
    result = subprocess.run(
        ["git", "log", "--oneline", f"{main_branch}..{branch_name}"],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode != 0 or bool(result.stdout.strip())


def reconcile_worktrees(
    repo_root: Path,
    project_root: Path,
    *,
    main_branch: str = "main",
    worktree_output: str | None = None,
    status_store: Any | None = None,
) -> list[JanitorDecision]:
    """Return cleanup decisions for linked worktrees of this project."""
    repo_root = Path(repo_root).resolve()
    project_root = Path(project_root).resolve()
    specs_dir = project_root / "specs"
    project_rel = project_root.relative_to(repo_root)
    if status_store is None and StatusStore is not None:
        status_store = StatusStore.for_specs_dir(specs_dir)

    records = (
        parse_worktree_list_porcelain(worktree_output)
        if worktree_output is not None
        else _list_worktrees(repo_root)
    )

    decisions: list[JanitorDecision] = []
    main_path = repo_root.resolve()
    for record in records:
        wt_path = record.path.resolve()
        if wt_path == main_path:
            continue
        branch_name = _branch_short_name(record.branch)
        spec_id = _spec_id_from_branch(branch_name)
        wt_project_root = wt_path / project_rel
        if not wt_project_root.exists():
            decisions.append(_decision(None, wt_path, branch_name, None, "skip", "foreign repo"))
            continue
        if spec_id is None:
            decisions.append(_decision(None, wt_path, branch_name, None, "skip", "unknown spec"))
            continue
        spec_path = _find_spec_file(specs_dir, spec_id)
        if spec_path is None:
            decisions.append(_decision(spec_id, wt_path, branch_name, None, "skip", "unknown spec"))
            continue

        status = _resolve_spec_status(spec_id, spec_path, status_store)
        decisions.append(_decide(spec_id, wt_path, branch_name, status, repo_root, main_branch))
    return decisions


def run_startup_janitor(
    repo_root: Path,
    project_root: Path,
    *,
    main_branch: str = "main",
    worktree_output: str | None = None,
    status_store: Any | None = None,
) -> list[JanitorDecision]:
    decisions = reconcile_worktrees(
        repo_root,
        project_root,
        main_branch=main_branch,
        worktree_output=worktree_output,
        status_store=status_store,
    )
    cleanup_decisions(repo_root, decisions)
    sweep_wip_heartbeats(project_root, status_store=status_store)
    return decisions


@dataclass(frozen=True)
class WipSweepDecision:
    spec_id: str | None
    path: Path
    status: str | None
    action: str  # "remove" | "keep"
    reason: str


def sweep_wip_heartbeats(
    project_root: Path,
    *,
    status_store: Any | None = None,
    now: float | None = None,
    max_age_days: int = WIP_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> list[WipSweepDecision]:
    """Sweep stale per-run files under reports/_wip/ for resolved specs.

    Heartbeats (`orchestrator-progress-<spec-id>.md`) of done specs are removed
    immediately; blocked/failed heartbeats and other per-run companion files of
    resolved specs are removed only past ``max_age_days`` (post-mortem value).
    Unknown spec IDs and unresolved specs are always kept. Files only.
    """
    project_root = Path(project_root).resolve()
    wip_dir = project_root / "reports" / "_wip"
    specs_dir = project_root / "specs"
    if not wip_dir.is_dir():
        return []
    if status_store is None and StatusStore is not None:
        status_store = StatusStore.for_specs_dir(specs_dir)
    now_s = time.time() if now is None else now
    max_age_s = max_age_days * 86400

    decisions: list[WipSweepDecision] = []
    for path in sorted(wip_dir.iterdir()):
        if not path.is_file():
            continue
        is_heartbeat = path.name.startswith(HEARTBEAT_PREFIX)
        if is_heartbeat:
            spec_id = path.name[len(HEARTBEAT_PREFIX):].removesuffix(".md")
        else:
            spec_id = _spec_id_from_branch(path.name.partition(".")[0])
        spec_path = _find_spec_file(specs_dir, spec_id) if spec_id else None
        if spec_path is None:
            decisions.append(WipSweepDecision(spec_id, path, None, "keep", "unknown spec"))
            continue
        status = _resolve_spec_status(spec_id, spec_path, status_store)
        if status not in GC_STATUSES:
            decisions.append(WipSweepDecision(spec_id, path, status, "keep", "status not resolved"))
            continue
        aged_out = (now_s - path.stat().st_mtime) > max_age_s
        if is_heartbeat and status == "done":
            decisions.append(WipSweepDecision(spec_id, path, status, "remove", "spec done"))
        elif aged_out:
            decisions.append(WipSweepDecision(spec_id, path, status, "remove", f"resolved, older than {max_age_days}d"))
        else:
            decisions.append(WipSweepDecision(spec_id, path, status, "keep", "resolved, within retention"))

    if not dry_run:
        for decision in decisions:
            if decision.action == "remove":
                decision.path.unlink(missing_ok=True)
    return decisions


def cleanup_decisions(repo_root: Path, decisions: Iterable[JanitorDecision]) -> list[str]:
    handles: list[WorktreeHandle] = []
    for decision in decisions:
        if decision.action != "gc" or not decision.spec_id:
            continue
        handles.append(
            WorktreeHandle(
                spec_id=decision.spec_id,
                worktree_path=decision.worktree_path,
                branch_name=decision.branch_name,
                events_dir=decision.worktree_path / ".nightshift" / "events",
                checkpoint_dir=decision.worktree_path / ".nightshift" / "checkpoints",
                status="completed",
            )
        )
    if not handles:
        return []
    return cleanup_worktrees(handles, Path(repo_root), force=True)


def cleanup_merged_worktree(
    spec_id: str,
    worktree_path: Path,
    branch_name: str,
    repo_root: Path,
    *,
    main_branch: str = "main",
) -> JanitorDecision:
    """Happy-path cleanup immediately after a done spec merge."""
    decision = _decide(spec_id, Path(worktree_path), branch_name, "done", Path(repo_root), main_branch)
    if decision.action == "gc":
        cleanup_decisions(repo_root, [decision])
    return decision


def _record_from_porcelain(data: dict[str, str]) -> WorktreeRecord:
    return WorktreeRecord(
        path=Path(data["worktree"]),
        branch=data.get("branch", ""),
        head=data.get("HEAD", ""),
    )


def _list_worktrees(repo_root: Path) -> list[WorktreeRecord]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return []
    return parse_worktree_list_porcelain(result.stdout)


def _branch_short_name(branch: str) -> str:
    return branch.removeprefix("refs/heads/") or "(detached)"


def _spec_id_from_branch(branch_name: str) -> str | None:
    """Extract a spec ID from a branch name, supporting project-prefixed IDs.

    Works for `nightshift/SPEC-123-janitor`, `nightshift/FART-SCR-132-002`,
    `nightshift/SPEC-CTX-MCP-008-slug` and bare `SPEC-42` alike: consume
    dash-separated uppercase/numeric tokens from the last path component and
    trim back to the last all-digit token. Lowercase tokens (slugs, agent
    hashes, ad-hoc branch names) never enter the ID.
    """
    component = branch_name.rsplit("/", 1)[-1]
    tokens: list[str] = []
    for token in component.split("-"):
        if not _ID_TOKEN_RE.fullmatch(token):
            break
        tokens.append(token)
    while tokens and not tokens[-1].isdigit():
        tokens.pop()
    if len(tokens) < 2:
        return None
    return "-".join(tokens)


def _find_spec_file(specs_dir: Path, spec_id: str) -> Path | None:
    matches = sorted(specs_dir.glob(f"{spec_id}*.md"))
    return matches[0] if matches else None


def _resolve_spec_status(spec_id: str, spec_path: Path, status_store: Any | None) -> str | None:
    if status_store is not None:
        state = status_store.get_state(spec_id)
        if state and state.get("status"):
            return str(state["status"])
    data = _read_frontmatter(spec_path)
    status = data.get("status")
    return str(status) if status else None


def _read_frontmatter(spec_path: Path) -> dict[str, Any]:
    text = spec_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    _, frontmatter, _ = text.split("---", 2)
    loaded = yaml.safe_load(frontmatter) or {}
    return loaded if isinstance(loaded, dict) else {}


def _decide(
    spec_id: str,
    worktree_path: Path,
    branch_name: str,
    status: str | None,
    repo_root: Path,
    main_branch: str,
) -> JanitorDecision:
    if status not in GC_STATUSES:
        return _decision(spec_id, worktree_path, branch_name, status, "keep", "status not resolved")
    if status in PINNED_STATUSES and (worktree_path / KEEP_MARKER).exists():
        return _decision(spec_id, worktree_path, branch_name, status, "keep", "keep marker")
    if is_unmerged(branch_name, repo_root, main_branch):
        return _decision(spec_id, worktree_path, branch_name, status, "manual", "unmerged — manual")
    return _decision(spec_id, worktree_path, branch_name, status, "gc", "resolved and merged")


def _decision(
    spec_id: str | None,
    worktree_path: Path,
    branch_name: str,
    status: str | None,
    action: str,
    reason: str,
) -> JanitorDecision:
    return JanitorDecision(spec_id, worktree_path, branch_name, status, action, reason)
