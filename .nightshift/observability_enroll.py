#!/usr/bin/env python3
"""Audit and migrate private Nightshift artifacts from public projects.

This is deliberately a planning tool.  Auditing never mutates Git; ordinary
migration only copies verified private artifacts and may perform a *future
index* cleanup after explicit operator approval.  History remediation is a
separate command and is dry-run by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from observability_store import ObservabilityStoreError, StoreContext, enroll

MANAGED_PUBLIC_PREFIXES = (
    ".nightshift/hooks/", ".nightshift/prompts/", ".nightshift/scenarios/",
)
# Kept in sync with CANONICAL_PROTOCOL_FILES in nightshift-sync.py (SPEC-191
# follow-up): that list is the single source of truth for what ships as
# public kit payload.  A file missing from here is classified "unknown" and
# blocks every audit/migrate run until someone resolves it, so update both
# lists together when the kit gains a new managed file.
MANAGED_PUBLIC_FILES = {
    ".nightshift/config.yaml", ".nightshift/STOP",
    ".nightshift/.gitignore", ".nightshift/BOOTSTRAP.md", ".nightshift/CHANGELOG.md",
    ".nightshift/README.md",
    ".nightshift/EXTENSIONS.md", ".nightshift/GIT.md", ".nightshift/HUMAN-REVIEW.md",
    ".nightshift/LOOP-DOMAIN-MAP.md", ".nightshift/LOOP.md", ".nightshift/ORCHESTRATOR.md",
    ".nightshift/REVIEW.md", ".nightshift/SPEC-GUIDE.md", ".nightshift/Skills/nightshift/SKILL.md",
    ".nightshift/VOCABULARY.md", ".nightshift/WATCHER.md", ".nightshift/ac_review.py",
    ".nightshift/analyze_metrics.py", ".nightshift/argo_home.py", ".nightshift/audit_nfr.py",
    ".nightshift/board.py", ".nightshift/board.sh", ".nightshift/check_followup_spec.py",
    ".nightshift/checkpoint.py", ".nightshift/circuit_breaker.py", ".nightshift/config-reference.yaml",
    ".nightshift/dependency_registry.py", ".nightshift/dispatch.py", ".nightshift/execution_history.py",
    ".nightshift/experiment_evidence.py", ".nightshift/experiment_protocol.py", ".nightshift/extension_checkpoint.py",
    ".nightshift/extension_checkpoint.sh", ".nightshift/extension_package.py", ".nightshift/extension_protocol.py",
    ".nightshift/extension_registry.py", ".nightshift/extension_runtime.py", ".nightshift/extension_sandbox.py",
    ".nightshift/failure_persistence.py", ".nightshift/fleet_metrics.py", ".nightshift/followup_decisions.py",
    ".nightshift/followup_metrics.py", ".nightshift/followup_processor.py", ".nightshift/goal_gate.py",
    ".nightshift/handler_registry.py", ".nightshift/hooks/commit-msg", ".nightshift/hooks/pre-commit",
    ".nightshift/integration_broker.py", ".nightshift/kickoff_reconciliation.py", ".nightshift/lifecycle.py",
    ".nightshift/loop_events.py", ".nightshift/loop_observability.py", ".nightshift/managed_payload_provenance.py",
    ".nightshift/metric-ranges.yaml", ".nightshift/metrics-schema.md", ".nightshift/metrics/_SCHEMA.md",
    ".nightshift/metrics_fidelity.py", ".nightshift/migrate_paths.py", ".nightshift/model_stylesheet.py",
    ".nightshift/nightshift-dag.py", ".nightshift/nightshift-instructions.py", ".nightshift/nightshift_coordinator.py",
    ".nightshift/observability_enroll.py", ".nightshift/observability_store.py", ".nightshift/outcome_router.py",
    ".nightshift/parallel_executor.py", ".nightshift/path_vars.py", ".nightshift/preflight.py",
    ".nightshift/private_state.py", ".nightshift/propagate_scores.py", ".nightshift/record_metrics.py",
    ".nightshift/recovery_convergence.py", ".nightshift/red_proof.py", ".nightshift/reflexion_producer.py",
    ".nightshift/release-manifest-unretained.json", ".nightshift/release.py", ".nightshift/release_coordinator.py",
    ".nightshift/release_handoff.py", ".nightshift/replay.py", ".nightshift/retry_loop.py",
    ".nightshift/run_validation.py", ".nightshift/scanner.py", ".nightshift/skill_tutorial.py",
    ".nightshift/source_fingerprints.py", ".nightshift/spec_frontmatter.py", ".nightshift/status_store.py",
    ".nightshift/synthesis_gate.py", ".nightshift/terminal_outcomes.py", ".nightshift/trace_export.py",
    ".nightshift/unblock_ladder.py", ".nightshift/unblock_spec.py", ".nightshift/validate_install.py",
    ".nightshift/validate_metrics.py", ".nightshift/validate_specs.py", ".nightshift/verification_report.py",
    ".nightshift/verifier_feedback.py", ".nightshift/vocabulary-registry.yaml", ".nightshift/vocabulary.py",
    ".nightshift/watchdog_cleanup.py", ".nightshift/worktree_janitor.py", ".nightshift/worktree_paths.py",
    ".nightshift/release-marker.json",
    # SPEC-383: drifted out before tests/test_observability_enroll.py guarded it.
    ".nightshift/artifact_reachability.py", ".nightshift/config_migrations.py",
    ".nightshift/deployment_tiers.py", ".nightshift/liveness_classifier.py",
    ".nightshift/resilience_ladder.py", ".nightshift/scope_guard.py",
    ".nightshift/spec_artifacts.py", ".nightshift/spec_promotion.py",
    ".nightshift/token_usage.py",
}
PRIVATE_PREFIXES = (
    ".nightshift/reports/", ".nightshift/metrics/", ".nightshift/knowledge/",
    ".nightshift/checkpoints/", ".nightshift/runs/", ".nightshift/outbox/",
)


class MigrationError(ObservabilityStoreError):
    """A migration precondition failed before a public Git mutation."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)
    if result.returncode:
        raise MigrationError(result.stderr.strip() or "git command failed")
    return result.stdout


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise MigrationError("unsafe Nightshift artifact path")
    return path.as_posix()


def classify_path(path: str) -> str:
    """Classify a repository-relative Nightshift path without consulting Git."""
    path = _safe_relative(path)
    if path in MANAGED_PUBLIC_FILES or path.startswith(MANAGED_PUBLIC_PREFIXES):
        return "managed_public_kit"
    if path.startswith(".nightshift/specs/") and path.endswith(".md"):
        return "public_spec"
    if path.startswith(PRIVATE_PREFIXES):
        return "private_artifact"
    return "unknown"


def _null_delimited(repo: Path, *args: str) -> set[str]:
    return {_safe_relative(item) for item in _git(repo, *args).split("\0") if item}


def _status_paths(repo: Path) -> tuple[set[str], set[str]]:
    staged: set[str] = set()
    working: set[str] = set()
    for line in _git(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines():
        if len(line) < 4:
            continue
        path = _safe_relative(line[3:].split(" -> ")[-1])
        working.add(path)
        if line[0] not in {" ", "?"}:
            staged.add(path)
    return staged, working


def audit_project(repo: Path) -> dict[str, Any]:
    """Return deterministic, non-mutating path evidence for a public project."""
    repo = Path(repo).resolve()
    root = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    tracked = _null_delimited(root, "ls-files", "-z")
    staged, working = _status_paths(root)
    history = _git(root, "rev-list", "--objects", "--all").splitlines()
    # rev-list emits '<oid> <path>'; only the latter is a repository path.
    history_paths = set()
    for item in history:
        _object_id, separator, path = item.partition(" ")
        if separator and path:
            history_paths.add(_safe_relative(path))
    candidates = sorted(
        path
        for path in tracked | staged | working | history_paths
        if path.startswith(".nightshift/")
        # ``rev-list --objects`` includes tree objects.  A directory is not an
        # artifact and must not turn its otherwise classified children unknown.
        and (path in tracked | staged | working or not (root / path).is_dir())
    )
    paths = []
    for path in candidates:
        paths.append({
            "path": path,
            "classification": classify_path(path),
            "tracked": path in tracked,
            "staged": path in staged,
            "working_tree": path in working,
            "reachable_history": path in history_paths,
        })
    unresolved = [item["path"] for item in paths if item["classification"] in {"private_artifact", "unknown"} and (item["tracked"] or item["staged"] or item["reachable_history"])]
    return {
        "schema_version": 1,
        "repository_fingerprint": hashlib.sha256(str(root).encode()).hexdigest(),
        "paths": paths,
        "unresolved_tracked_private_artifacts": sorted(unresolved),
        "audit_clean": not unresolved,
        "rerun_command": f"python3 observability_enroll.py audit --repo {root}",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_sources(repo: Path, audit: dict[str, Any]) -> list[tuple[str, Path]]:
    sources = []
    for item in audit["paths"]:
        if item["classification"] != "private_artifact":
            continue
        source = repo / item["path"]
        if not source.exists():
            continue
        if source.is_symlink() or not source.is_file():
            raise MigrationError("private artifact must be an existing non-symlink regular file")
        sources.append((item["path"], source))
    return sources


def copy_private_artifacts(context: StoreContext, audit: dict[str, Any]) -> dict[str, Any]:
    """Copy regular private files into the verified private root and hash verify them."""
    if any(item["classification"] == "unknown" for item in audit["paths"]):
        raise MigrationError("ambiguous Nightshift path classification; refusing migration")
    sources = _private_sources(context.repo, audit)
    migration_id = str(uuid.uuid4())
    base = context.root / "nightshift-observability" / "projects" / context.project_id / "migrations" / migration_id
    if base.exists() or base.is_symlink():
        raise MigrationError("private migration target already exists or is unsafe")
    records = []
    try:
        for relative, source in sources:
            target = base / "artifacts" / _safe_relative(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target, follow_symlinks=False)
            source_hash, target_hash = _sha256(source), _sha256(target)
            if source_hash != target_hash:
                raise MigrationError("private artifact hash verification failed")
            records.append({"path": relative, "sha256": source_hash, "bytes": source.stat().st_size})
        manifest = {
            "schema_version": 1, "project_id": context.project_id,
            "migration_id": migration_id, "created_at": datetime.now(UTC).isoformat(),
            "artifacts": records,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        (base / "manifest.json").write_bytes(manifest_bytes)
    except Exception:
        shutil.rmtree(base, ignore_errors=True)
        raise
    return {"migration_id": migration_id, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "artifacts": records}


def cleanup_future_index(repo: Path, paths: Iterable[str], *, operator_approved: bool) -> str | None:
    """Commit an approved future-index removal.  It never force-adds ignored files."""
    if not operator_approved:
        raise MigrationError("future-index cleanup requires explicit operator approval")
    paths = sorted({_safe_relative(path) for path in paths})
    if not paths or any(classify_path(path) != "private_artifact" for path in paths):
        raise MigrationError("cleanup accepts only explicit private artifacts")
    repo = Path(repo).resolve()
    staged_before, _ = _status_paths(repo)
    if staged_before:
        raise MigrationError("cleanup refuses an already staged index")
    result = subprocess.run(["git", "-C", str(repo), "rm", "--cached", "--", *paths], text=True, capture_output=True)
    if result.returncode:
        raise MigrationError(result.stderr.strip() or "git rm --cached failed")
    message = "[SPEC-191] chore: remove private Nightshift artifacts from future index"
    result = subprocess.run(["git", "-C", str(repo), "commit", "-m", message, "--", *paths], text=True, capture_output=True)
    if result.returncode:
        raise MigrationError(result.stderr.strip() or "approved cleanup commit failed")
    return _git(repo, "rev-parse", "HEAD").strip()


def migrate_project(config: Path, repo: Path, *, approve_cleanup: bool = False) -> dict[str, Any]:
    """Copy first, then optionally commit the reviewed future-index cleanup."""
    audit = audit_project(repo)
    context = enroll(config, repo)
    copied = copy_private_artifacts(context, audit)
    cleanup_paths = [item["path"] for item in audit["paths"] if item["classification"] == "private_artifact" and item["tracked"]]
    commit = cleanup_future_index(repo, cleanup_paths, operator_approved=True) if approve_cleanup and cleanup_paths else None
    return {
        "project_id": context.project_id, "private_manifest_sha256": copied["manifest_sha256"],
        "public_cleanup_commit": commit, "history_remediation_state": "not_started",
        "safe_rerun_command": f"python3 observability_enroll.py migrate --repo {Path(repo).resolve()} --config {Path(config).resolve()}",
        "audit": audit,
    }


def history_remediation(repo: Path, *, apply: bool = False, operator_authority: str | None = None) -> dict[str, Any]:
    """Inventory history leaks; apply is intentionally blocked pending a reviewed rewrite tool."""
    if apply and not operator_authority:
        raise MigrationError("history remediation apply requires explicit operator authority")
    audit = audit_project(repo)
    refs = [line for line in _git(repo, "for-each-ref", "--format=%(refname)").splitlines() if line]
    result = {"mode": "dry-run", "affected_refs": refs, "leak_paths": audit["unresolved_tracked_private_artifacts"], "mutated": False}
    if apply:
        raise MigrationError("history rewrite requires a separately reviewed rewrite tool; no rewrite was run")
    return result


def release_disposition(install: Path) -> dict[str, str] | None:
    """Return a safe release skip for enrolled projects with unresolved artifacts."""
    config = Path(install) / "config.yaml"
    if not config.is_file() or "sink: private-dropbox" not in config.read_text(errors="replace"):
        return None
    audit = audit_project(Path(install))
    if audit["audit_clean"]:
        return None
    return {"classification": "tracked_private_artifacts_unresolved", "reason": "run SPEC-191 migration before fleet release", "migration_reference": audit["rerun_command"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("audit", "migrate", "history-remediation"):
        item = sub.add_parser(name)
        item.add_argument("--repo", type=Path, required=True)
    migrate = sub.choices["migrate"]
    migrate.add_argument("--config", type=Path, required=True)
    migrate.add_argument("--approve-future-index-cleanup", action="store_true")
    history = sub.choices["history-remediation"]
    history.add_argument("--apply", action="store_true")
    history.add_argument("--operator-authority")
    args = parser.parse_args()
    if args.command == "audit": result = audit_project(args.repo)
    elif args.command == "migrate": result = migrate_project(args.config, args.repo, approve_cleanup=args.approve_future_index_cleanup)
    else: result = history_remediation(args.repo, apply=args.apply, operator_authority=args.operator_authority)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
