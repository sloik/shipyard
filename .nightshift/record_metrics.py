#!/usr/bin/env python3
"""
record_metrics.py — single-call per-spec metrics emission for the Nightshift loop.

Why this exists (SPEC-067 / canonical audit 2026-05-28):
    Step 13 previously asked the *model* to hand-author a ~60-field metrics YAML.
    Across real projects that step was honored in ~2% of runs — the busiest project
    (Cortex/api) produced 102 reports but 2 metric files. Hand-authoring a large
    schema is the first thing a loaded or less-capable model drops.

    This script moves the authoring burden from the model to deterministic code.
    The model supplies only what it actually knows (status, test counts, review
    cycles, failure info); everything derivable is derived:
        from git    -> files_changed, lines_added, lines_removed, commit hash + message
        from config -> model, harness, loop_version, review_mode
        computed    -> satisfaction dimensions, overall_score, classification

    It emits the SAME schema validate_metrics.py / analyze_metrics.py already
    consume (no consumer breaks), plus one additive field: `outcome` — a
    controlled vocabulary (done | partial | blocked | noop) that makes reports and
    metrics minable. For non-`completed` runs it also appends a one-line entry to
    failure-ledger.json so the failure path stops being invisible.

Usage:
    python3 record_metrics.py \
        --spec-id SPEC-XXX --spec-file specs/SPEC-XXX.md \
        --status completed --outcome done \
        --started-at 2026-05-28T10:00:00Z --completed-at 2026-05-28T10:45:00Z \
        --tests-total 18 --tests-passed 18 \
        [--lint-errors 0] [--type-errors 0] [--build-pass true] \
        [--review-cycles 1] [--completion-score 1.0] \
        [--files-read 0] [--knowledge-used 0] \
        [--patterns-written 0 --patterns-injected 0 --patterns-cited 0] \
        [--domain code] [--execution-mode sequential] \
        [--error-type test_failure --error-desc "..."]   # required when status != completed
        [--metrics-dir .nightshift/metrics] [--config .nightshift/config.yaml] \
        [--repo .] [--dry-run]

Exit codes:
    0 — metrics file written (and ledger appended if applicable)
    2 — bad arguments (e.g. non-completed status without --error-type/--error-desc)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# status enum accepted by analyze_metrics.py / validate_metrics.py
STATUS_ENUM = {"completed", "failed", "blocked", "discarded", "partial"}
# additive controlled vocabulary for reports + cross-run mining
OUTCOME_ENUM = {"done", "partial", "blocked", "noop"}
EVIDENCE_RESULT_ENUM = {"pass", "fail", "unknown"}
BLOCKER_CLASS_ENUM = {
    "none",
    "implementation",
    "test_infrastructure",
    "fixture_drift",
    "baseline_regression",
    "external_input",
    "evidence_gap",
    "unknown",
}
BLOCKER_SCOPE_ENUM = {"none", "in_scope", "out_of_scope", "mixed", "unknown"}

# SPEC-130: emission-time vocabulary normalization. VOCABULARY.md is the
# instruction; this table is the mechanism. Synonyms observed in the
# 2026-07-02 cross-project corpus (381 rows, 16 installs).
STATUS_ALIASES = {
    "done": "completed",
    "complete": "completed",
    "implemented": "completed",
    "success": "completed",
    "passed": "completed",
    "fail": "failed",
    "error": "failed",
}
# Model spellings → canonical id (case-insensitive lookup on the raw string).
MODEL_ALIASES = {
    "gpt-5 codex": "gpt-5-codex",
    "gpt5-codex": "gpt-5-codex",
    "codex-gpt-5": "gpt-5-codex",
    "codex": "gpt-5-codex",
}


def normalize_status(raw) -> tuple[str, str | None]:
    """Map a status synonym to the canonical enum (SPEC-130 R1).

    Returns (status, status_raw): status_raw is None when no mapping was
    needed. Out-of-vocab values pass through unchanged with a loud warning,
    preserving the original in status_raw.
    """
    s = str(raw or "").strip()
    lowered = s.lower()
    if lowered in STATUS_ENUM:
        return lowered, None if lowered == s else s
    if lowered in STATUS_ALIASES:
        return STATUS_ALIASES[lowered], s
    print(
        f"Warning: status '{s}' is outside VOCABULARY.md canonical set "
        f"{sorted(STATUS_ENUM)} — passing through, preserved in status_raw",
        file=sys.stderr,
    )
    return s, s


def _usable_model(value) -> bool:
    return str(value or "").strip().lower() not in ("", "?", "unknown")


def normalize_model(raw) -> tuple[str, str | None]:
    """Normalize a model string (SPEC-130 R2): case-fold + alias table.

    Returns (model, model_raw): model_raw is None when nothing changed.
    """
    s = str(raw or "").strip()
    if not _usable_model(s):
        return "unknown", s if s and s != "unknown" else None
    lowered = s.lower()
    canonical = MODEL_ALIASES.get(lowered, lowered)
    return canonical, s if canonical != s else None
# Fallback root-cause / suggestion text by error_type. Mirrors the small table in
# knowledge_writer.py so a failure row stays validate_metrics-compatible without
# forcing the model to author diagnosis prose. Overridable via CLI flags.
_ROOT_CAUSE_BY_ERROR_TYPE = {
    "test_failure": "One or more tests did not pass",
    "test_hang": "A test did not terminate within the time budget",
    "build_broken": "The build did not complete successfully",
    "build_error": "The build did not complete successfully",
    "type_error": "Static type checking reported errors",
    "lint_error": "The linter reported errors",
    "eval_timeout": "Eval exceeded configured time budget",
    "eval_run_failed": "Eval harness reported a non-success status",
    "timeout": "Step exceeded its time budget",
}
_SUGGESTION_BY_ERROR_TYPE = {
    "test_failure": "Inspect the failing assertion and fix the code or the test",
    "test_hang": "Add a timeout, reduce scope, or fix the non-terminating path",
    "build_broken": "Read the build log and resolve the first error",
    "build_error": "Read the build log and resolve the first error",
    "type_error": "Resolve the reported type mismatches",
    "lint_error": "Run the formatter/linter and address the findings",
    "eval_timeout": "Raise time budget, reduce eval scope, or switch to a faster model",
    "eval_run_failed": "Inspect the eval result payload and rerun",
    "timeout": "Increase the budget or split the work",
}

# satisfaction dimension weights (unchanged from the historical schema)
WEIGHTS = {
    "tests": 3,
    "lint": 1,
    "type_check": 1,
    "build": 2,
    "completion_verification": 3,
    "review": 2,
}


def _run_git(repo: Path, args: list[str]) -> str:
    """Run a git command, returning stripped stdout or '' on any failure."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, ValueError):
        return ""


def derive_git(repo: Path) -> dict:
    """Derive commit hash/message and changed-line counts from the latest commit."""
    commit_hash = _run_git(repo, ["log", "-1", "--format=%H"]) or "unknown"
    commit_message = _run_git(repo, ["log", "-1", "--format=%s"]) or "unknown"
    files_changed = lines_added = lines_removed = 0
    numstat = _run_git(repo, ["show", "--numstat", "--format=", "HEAD"])
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, _path = parts
        files_changed += 1
        if added.isdigit():
            lines_added += int(added)
        if removed.isdigit():
            lines_removed += int(removed)
    return {
        "commit_hash": commit_hash,
        "commit_message": commit_message,
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


def derive_config(config_path: Path, model_override: str = "", harness_override: str = "") -> dict:
    """Resolve model/harness/loop_version/review_mode.

    Precedence for model & harness: explicit override > config.yaml > "unknown".
    `runtime.model` is intentionally blank in the template ("filled at runtime"),
    so the running model passes its own name via --model — without that the model
    field stays empty and cross-model comparison (the reason metrics exist) breaks.
    """
    defaults = {
        "model": "unknown",
        "harness": "unknown",
        "loop_version": "unknown",
        "review_mode": "self",
    }
    # config.yaml may be a multi-document YAML (the canonical template uses `---`
    # section separators), so merge every document's top-level keys rather than
    # failing on safe_load's single-document assumption.
    cfg = {}
    if config_path.is_file():
        try:
            for doc in yaml.safe_load_all(config_path.read_text()):
                if isinstance(doc, dict):
                    cfg.update(doc)
        except yaml.YAMLError:
            cfg = {}
    runtime = cfg.get("runtime", {}) or {}
    review = cfg.get("review", {}) or {}
    # SPEC-130 R3: '?'/'unknown'/blank never win the precedence chain — fall
    # through override (commit trailer) → config → literal "unknown".
    raw_model = next(
        (m for m in (model_override, runtime.get("model")) if _usable_model(m)),
        defaults["model"],
    )
    model, model_raw = normalize_model(raw_model)
    return {
        "model": model,
        "model_raw": model_raw,
        "harness": str(harness_override or runtime.get("harness") or defaults["harness"]),
        "loop_version": str(runtime.get("loop_version") or defaults["loop_version"]),
        "review_mode": str(review.get("mode") or defaults["review_mode"]),
    }


def compute_satisfaction(
    *,
    tests_total: int,
    tests_passed: int,
    lint_errors: int,
    type_errors: int,
    build_pass: bool,
    completion_score: float,
    review_cycles: int,
) -> dict:
    """Compute the weighted satisfaction block from objective inputs."""
    tests = 1.0 if tests_total == 0 else round(tests_passed / tests_total, 3)
    lint = 1.0 if lint_errors == 0 else 0.3
    type_check = 1.0 if type_errors == 0 else 0.3
    build = 1.0 if build_pass else 0.0
    completion = max(0.0, min(1.0, completion_score))
    review = 1.0 if review_cycles <= 1 else max(0.5, 1.0 - 0.1 * (review_cycles - 1))

    scores = {
        "tests": tests,
        "lint": lint,
        "type_check": type_check,
        "build": build,
        "completion_verification": completion,
        "review": round(review, 3),
    }
    weighted = sum(scores[d] * WEIGHTS[d] for d in WEIGHTS)
    overall = round(weighted / sum(WEIGHTS.values()), 3)
    classification = "high" if overall >= 0.8 else "medium" if overall >= 0.5 else "low"
    return {
        "overall_score": overall,
        "classification": classification,
        "dimensions": {d: {"score": scores[d], "weight": WEIGHTS[d]} for d in WEIGHTS},
    }


def build_metrics(args, git: dict, cfg: dict) -> dict:
    """Assemble the full schema-valid metrics mapping."""
    test_pass_rate = (
        1.0 if args.tests_total == 0 else round(args.tests_passed / args.tests_total, 3)
    )
    status, status_raw = normalize_status(args.status)
    if status_raw is None:
        status_raw = getattr(args, "status_raw", None)
    metrics = {
        "task_id": args.spec_id,
        "spec_file": args.spec_file,
        "started_at": args.started_at,
        "completed_at": args.completed_at,
        "status": status,
        "outcome": args.outcome,
        "domain": args.domain,
        "loop_version": cfg["loop_version"],
        "model": cfg["model"],
        "harness": cfg["harness"],
        "review_mode": cfg["review_mode"],
        "phases": {
            "execution_mode": args.execution_mode,
            "preflight": {"clean_tree": True, "initial_tests_pass": True, "duration_s": 0},
            "context_load": {
                "files_read": args.files_read,
                "knowledge_entries_used": args.knowledge_used,
                "duration_s": 0,
            },
            "test_planning": {"duration_s": 0},
            "test_writing": {
                "tests_written": args.tests_total,
                "tests_failing": max(0, args.tests_total - args.tests_passed),
                "duration_s": 0,
            },
            "implementation": {
                "files_created": 0,
                "files_modified": git["files_changed"],
                "lines_added": git["lines_added"],
                "lines_removed": git["lines_removed"],
                "duration_s": 0,
            },
            "review": {"cycles": args.review_cycles, "issues_found": []},
            "validation": {
                "build_pass": args.build_pass,
                "build_errors": 0,
                "test_pass_rate": test_pass_rate,
                "tests_total": args.tests_total,
                "tests_passed": args.tests_passed,
                "lint_errors": args.lint_errors,
                "type_errors": args.type_errors,
                "duration_s": 0,
            },
            "completion_verification": {
                "acceptance_criteria_met": status == "completed",
                "no_regression": True,
            },
        },
        "satisfaction": compute_satisfaction(
            tests_total=args.tests_total,
            tests_passed=args.tests_passed,
            lint_errors=args.lint_errors,
            type_errors=args.type_errors,
            build_pass=args.build_pass,
            completion_score=args.completion_score,
            review_cycles=args.review_cycles,
        ),
        "commit": {"hash": git["commit_hash"], "message": git["commit_message"]},
    }
    if status_raw is not None:
        metrics["status_raw"] = status_raw
    if cfg.get("model_raw"):
        metrics["model_raw"] = cfg["model_raw"]

    if status == "completed":
        injected = args.patterns_injected
        metrics["knowledge"] = {
            "pattern_written": args.patterns_written,
            "patterns_injected": injected,
            "patterns_cited": args.patterns_cited,
            "citation_rate": round(args.patterns_cited / injected, 3) if injected else 0,
        }
    else:
        generic_cause = f"Run ended with status '{status}'"
        generic_fix = "Inspect the run logs and address the first failure"
        metrics["failure"] = {
            "phase": args.error_phase or "validation",
            "error_type": args.error_type,
            "description": args.error_desc,
            "root_cause": args.error_root_cause
            or _ROOT_CAUSE_BY_ERROR_TYPE.get(args.error_type, generic_cause),
            "suggestion": args.error_suggestion
            or _SUGGESTION_BY_ERROR_TYPE.get(args.error_type, generic_fix),
        }
    return metrics


def append_failure_ledger(ledger_path: Path, args, now: str, dry_run: bool) -> None:
    """Append a minimal failure record (matches metrics-schema.md minimal form)."""
    entry = {
        "timestamp": now,
        "status": args.status,
        "raw_status": None,
        "source_file": args.spec_file,
        "error_type": args.error_type,
        "description": args.error_desc,
        "details": {"spec_id": args.spec_id, "outcome": args.outcome},
        "spec_file": args.spec_file,
    }
    if dry_run:
        print(
            f"[dry-run] would append failure-ledger entry: {entry['error_type']}",
            file=sys.stderr,
        )
        return
    existing = []
    if ledger_path.is_file():
        try:
            existing = json.loads(ledger_path.read_text()) or []
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []
    existing.append(entry)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(existing, indent=2) + "\n")


def next_sequence(metrics_dir: Path, date: str) -> str:
    """Return a zero-padded 3-digit sequence for today's metrics files."""
    if not metrics_dir.is_dir():
        return "001"
    n = sum(1 for _ in metrics_dir.glob(f"{date}_*.yaml")) + 1
    return f"{n:03d}"


# ---------------------------------------------------------------------------
# Mark-commit mode (SPEC-086): emit metrics MECHANICALLY at the parent's
# main-side `chore: mark <id> done|blocked` commit, with zero agent-supplied
# args. SPEC-067's record_metrics still needed the agent to *invoke* it with
# run-only args at the end of a run — a droppable terminal step (audit 2026-06-14
# measured 1.6% capture). This path is invoked by hooks/post-commit so the agent
# is not in the loop. Everything is derived from git + the spec's report.
# ---------------------------------------------------------------------------

MARK_COMMIT_RE = re.compile(r"^chore: mark (SPEC-(?:[A-Z0-9]+-)*\d+) (done|blocked)$")
_REPORT_TESTS_RE = re.compile(r"[Tt]ests?\s+passed:?\s*(\d+)\s*/\s*(\d+)")


def _changed_files(repo: Path, ref: str) -> list[str]:
    """Files touched by a single commit (repo-relative paths)."""
    out = _run_git(repo, ["show", "--name-only", "--format=", ref])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def find_in_progress_sha(repo: Path, spec_id: str, before: str) -> str:
    """Most-recent `chore: mark <spec_id> in_progress` commit at or before `before`."""
    out = _run_git(repo, ["log", "--format=%H %s", "-n", "1000", before])
    target = f"chore: mark {spec_id} in_progress"
    for line in out.splitlines():
        sha, _, subj = line.partition(" ")
        if subj.strip() == target:
            return sha
    return ""


def commit_iso(repo: Path, ref: str) -> str:
    """Committer date of `ref` in ISO-8601, or '' on failure."""
    return _run_git(repo, ["log", "-1", "--format=%cI", ref]) or ""


def commit_trailer(repo: Path, ref: str, key: str) -> str:
    """Return one Git trailer value from ``ref``, stripped."""
    return _run_git(
        repo,
        ["log", "-1", f"--format=%(trailers:key={key},valueonly,separator=)", ref],
    ).strip()


def _bounded_int(value: str, default: int = 0) -> int:
    """Parse a non-negative integer trailer, using ``default`` when malformed."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def derive_resolution(
    repo: Path,
    spec_id: str,
    mark_commit: str,
    in_progress_sha: str,
    final_outcome: str,
) -> dict:
    """Derive the parent-authoritative kickoff resolution from git history.

    The in-progress commit is the stable run identity. Repeated blocked/done
    transitions for that run become ordered attempts, so a later recovery does
    not overwrite or fragment the original kickoff outcome.
    """
    run_id = in_progress_sha or (
        _run_git(repo, ["rev-parse", mark_commit]) or mark_commit
    )
    history_range = f"{run_id}..{mark_commit}" if in_progress_sha else mark_commit
    history = _run_git(repo, ["log", "--reverse", "--format=%H%x09%s", history_range])
    transitions = []
    for line in history.splitlines():
        sha, _, subject = line.partition("\t")
        match = MARK_COMMIT_RE.match(subject)
        if match and match.group(1) == spec_id:
            transitions.append((sha, match.group(2)))
    current_sha = _run_git(repo, ["rev-parse", mark_commit]) or mark_commit
    current_index = next(
        (i for i, (sha, _) in enumerate(transitions) if sha == current_sha),
        len(transitions) - 1,
    )
    prior_outcome = transitions[current_index - 1][1] if current_index > 0 else "none"
    stage = "recovery" if any(
        outcome == "blocked" for _, outcome in transitions[:current_index]
    ) else "kickoff_gate"

    default_evidence = "pass" if final_outcome == "done" else "unknown"
    evidence_keys = {
        "report_exists": "Nightshift-Evidence-Report",
        "tests_passed": "Nightshift-Evidence-Tests",
        "code_changed": "Nightshift-Evidence-Code",
        "acs_covered": "Nightshift-Evidence-ACs",
    }
    evidence_gate = {}
    for field, trailer_key in evidence_keys.items():
        value = commit_trailer(repo, mark_commit, trailer_key).lower()
        evidence_gate[field] = (
            value if value in EVIDENCE_RESULT_ENUM else default_evidence
        )

    blocker_class = commit_trailer(
        repo, mark_commit, "Nightshift-Blocker-Class"
    ).lower()
    blocker_scope = commit_trailer(
        repo, mark_commit, "Nightshift-Blocker-Scope"
    ).lower()
    blocker_class = blocker_class if blocker_class in BLOCKER_CLASS_ENUM else (
        "none" if final_outcome == "done" else "unknown"
    )
    blocker_scope = blocker_scope if blocker_scope in BLOCKER_SCOPE_ENUM else (
        "none" if final_outcome == "done" else "unknown"
    )
    unblock_attempts = _bounded_int(
        commit_trailer(repo, mark_commit, "Nightshift-Unblock-Attempts")
    )
    unblock_limit = _bounded_int(
        commit_trailer(repo, mark_commit, "Nightshift-Unblock-Limit")
    )

    started = datetime.fromisoformat(commit_iso(repo, run_id).replace("Z", "+00:00"))
    completed = datetime.fromisoformat(
        commit_iso(repo, mark_commit).replace("Z", "+00:00")
    )
    return {
        "run_id": run_id,
        "stage": stage,
        "attempt": current_index + 1,
        "prior_outcome": prior_outcome,
        "final_outcome": final_outcome,
        "evidence_gate": evidence_gate,
        "blocker_class": blocker_class,
        "blocker_scope": blocker_scope,
        "unblock_attempts": unblock_attempts,
        "unblock_limit": unblock_limit,
        "automatic_unblock_succeeded": (
            final_outcome == "done"
            and prior_outcome == "none"
            and unblock_attempts > 0
        ),
        "later_session_required": stage == "recovery",
        "resolution_latency_s": max(0.0, (completed - started).total_seconds()),
    }


def derive_local_resolution(
    store,
    spec_id: str,
    run_id: str,
    *,
    evidence_gate: dict[str, str] | None = None,
) -> dict:
    """Derive kickoff resolution from one durable private-local lifecycle event.

    This is the local-event counterpart to :func:`derive_resolution`. It intentionally
    accepts an existing ``StatusStore`` instance so attribution never consults Git history.
    """
    events = [
        event
        for event in store.get_run_history(spec_id, run_id)
        if event.get("source") == "private-local-coordinator"
    ]
    if not events:
        raise ValueError(f"no durable lifecycle events for {spec_id} run {run_id}")
    started = next((event for event in events if event.get("status") == "in_progress"), None)
    terminal = next(
        (event for event in reversed(events) if event.get("status") in {"done", "blocked"}),
        None,
    )
    if started is None:
        raise ValueError(f"run {run_id} has no durable in_progress event")
    if terminal is None:
        raise ValueError(f"run {run_id} has not reached a terminal state")
    final_outcome = str(terminal["status"])
    payload = terminal.get("payload") or {}
    default_evidence = "pass" if final_outcome == "done" else "unknown"
    supplied = evidence_gate or payload.get("evidence_gate") or {}
    evidence = {
        key: supplied.get(key, default_evidence)
        if supplied.get(key, default_evidence) in EVIDENCE_RESULT_ENUM
        else default_evidence
        for key in ("report_exists", "tests_passed", "code_changed", "acs_covered")
    }
    started_at = datetime.fromisoformat(str(started["created_at"]).replace("Z", "+00:00"))
    completed_at = datetime.fromisoformat(str(terminal["created_at"]).replace("Z", "+00:00"))
    unblock_attempts = _bounded_int(str(payload.get("unblock_attempts", 0)))
    unblock_limit = _bounded_int(str(payload.get("unblock_limit", 0)))
    return {
        "run_id": run_id,
        "stage": str(payload.get("stage") or "kickoff_gate"),
        "attempt": _bounded_int(str(payload.get("attempt", 1)), default=1),
        "prior_outcome": str(payload.get("prior_outcome") or "none"),
        "final_outcome": final_outcome,
        "evidence_gate": evidence,
        "blocker_class": str(payload.get("blocker_class") or ("none" if final_outcome == "done" else "unknown")),
        "blocker_scope": str(payload.get("blocker_scope") or ("none" if final_outcome == "done" else "unknown")),
        "unblock_attempts": unblock_attempts,
        "unblock_limit": unblock_limit,
        "automatic_unblock_succeeded": final_outcome == "done" and unblock_attempts > 0,
        "later_session_required": str(payload.get("stage") or "kickoff_gate") == "recovery",
        "resolution_latency_s": max(0.0, (completed_at - started_at).total_seconds()),
    }


def derive_git_span(repo: Path, base: str, head: str, scope: str = "") -> dict:
    """Like derive_git() but diffs base..head (the real spec work span), optionally
    scoped to a directory, and reads the commit identity from `head` rather than HEAD.
    Falls back to `git show head` when no base is known."""
    commit_hash = _run_git(repo, ["log", "-1", "--format=%H", head]) or head
    commit_message = _run_git(repo, ["log", "-1", "--format=%s", head]) or "unknown"
    files_changed = lines_added = lines_removed = 0
    if base:
        args = ["diff", "--numstat", f"{base}..{head}"]
        if scope:
            args += ["--", scope]
        numstat = _run_git(repo, args)
    else:
        numstat = _run_git(repo, ["show", "--numstat", "--format=", head])
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, _path = parts
        files_changed += 1
        if added.isdigit():
            lines_added += int(added)
        if removed.isdigit():
            lines_removed += int(removed)
    return {
        "commit_hash": commit_hash,
        "commit_message": commit_message,
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


def parse_report_tests(reports_dir: Path, spec_id: str) -> tuple[int, int]:
    """Best-effort (total, passed) from the newest report naming this spec.
    Returns (0, 0) if no machine-readable `Tests passed: X/Y` line is found —
    a present-but-coarse row beats an absent one (audit R1)."""
    if not reports_dir.is_dir():
        return (0, 0)
    candidates = sorted(reports_dir.glob(f"*{spec_id}*.md"), reverse=True)
    for rep in candidates:
        try:
            m = _REPORT_TESTS_RE.search(rep.read_text())
        except OSError:
            continue
        if m:
            return (int(m.group(2)), int(m.group(1)))  # (total, passed)
    return (0, 0)


def existing_metrics_for_commit(metrics_dir: Path, spec_id: str, commit_hash: str) -> bool:
    """Idempotency guard: True if a metrics file for this spec already records this
    commit hash — so a re-fired hook (or an agent that already emitted richly) is
    not clobbered/duplicated."""
    if not metrics_dir.is_dir():
        return False
    for f in metrics_dir.glob(f"*_{spec_id}.yaml"):
        try:
            data = yaml.safe_load(f.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and (data.get("commit") or {}).get("hash") == commit_hash:
            return True
    return False


def derive_block_reason(spec_file: Path) -> str:
    """Pull a 'Block Reason' line from the spec body for the failure ledger, if present."""
    try:
        text = spec_file.read_text()
    except OSError:
        return ""
    m = re.search(r"(?im)^.*?block\s*reason[:\s]+(.+)$", text)
    return m.group(1).strip()[:200] if m else ""


def main_mark_commit(argv) -> int:
    """Derive + emit a metrics row from a `chore: mark <id> done|blocked` commit.

    No-ops (exit 0) on any commit that is not a mark-done/blocked, or that cannot be
    routed to an install. Idempotent. Never raises into the caller's hook.
    """
    p = argparse.ArgumentParser(description="Emit metrics from a mark-done/blocked commit.")
    p.add_argument("--mark-commit", required=True, help="commit SHA (e.g. HEAD)")
    p.add_argument("--repo", default=".")
    p.add_argument("--model", default="")
    p.add_argument("--harness", default="")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    repo = Path(args.repo)
    subject = _run_git(repo, ["log", "-1", "--format=%s", args.mark_commit])
    m = MARK_COMMIT_RE.match(subject)
    if not m:
        return 0  # not a mark-done/blocked commit — silent no-op (the common case)
    spec_id, mark_word = m.group(1), m.group(2)
    outcome = mark_word  # done | blocked
    status = "completed" if mark_word == "done" else "blocked"

    # Route to the install from the spec file changed in this commit.
    spec_rel = next(
        (f for f in _changed_files(repo, args.mark_commit)
         if "/specs/" in f and f.endswith(".md")),
        "",
    )
    if not spec_rel:
        return 0  # cannot route without a spec file in the commit
    spec_path = repo / spec_rel
    install_dir = spec_path.parent.parent          # <install>/specs/X.md -> <install>
    metrics_dir = install_dir / "metrics"
    config_path = install_dir / "config.yaml"
    reports_dir = install_dir / "reports"

    commit_hash = _run_git(repo, ["rev-parse", args.mark_commit]) or args.mark_commit
    if not args.dry_run and existing_metrics_for_commit(metrics_dir, spec_id, commit_hash):
        print(f"[mark-commit] metrics already recorded for {spec_id} @ {commit_hash[:8]}")
        return 0

    in_progress_sha = find_in_progress_sha(repo, spec_id, args.mark_commit)
    started_at = commit_iso(repo, in_progress_sha) if in_progress_sha else commit_iso(repo, args.mark_commit)
    completed_at = commit_iso(repo, args.mark_commit)
    # Prefer authoritative validation.json (SPEC-092) over best-effort report-parsing.
    vjson = metrics_dir / f"{spec_id}.validation.json"
    lint_errors = type_errors = 0
    build_pass = True
    if vjson.is_file():
        try:
            v = json.loads(vjson.read_text())
            tests_total = int(v.get("tests_total", 0))
            tests_passed = int(v.get("tests_passed", 0))
            lint_errors = int(v.get("lint_errors", 0))
            type_errors = int(v.get("type_errors", 0))
            build_pass = bool(v.get("build_pass", True))
        except (OSError, json.JSONDecodeError, ValueError):
            tests_total, tests_passed = parse_report_tests(reports_dir, spec_id)
    else:
        tests_total, tests_passed = parse_report_tests(reports_dir, spec_id)
    git = derive_git_span(repo, in_progress_sha, args.mark_commit, scope=str(install_dir))
    # Model attribution (audit F3): the parent MAY add a `Nightshift-Model: <id>` trailer
    # to the mark-done commit so the row is model-attributed. The hook can't otherwise
    # know which model ran. Best-effort: precedence trailer > --model > config > "unknown".
    model_trailer = _run_git(
        repo,
        ["log", "-1", "--format=%(trailers:key=Nightshift-Model,valueonly,separator=)", args.mark_commit],
    ).strip()
    cfg = derive_config(config_path, model_override=args.model or model_trailer, harness_override=args.harness)

    ns = SimpleNamespace(
        spec_id=spec_id,
        spec_file=spec_rel,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        outcome=outcome,
        domain="code",
        execution_mode="sequential",
        files_read=0,
        knowledge_used=0,
        tests_total=tests_total,
        tests_passed=tests_passed,
        review_cycles=1,
        build_pass=build_pass,
        lint_errors=lint_errors,
        type_errors=type_errors,
        completion_score=1.0 if status == "completed" else 0.0,
        patterns_written=0,
        patterns_injected=0,
        patterns_cited=0,
        error_phase="validation",
        error_type="" if status == "completed" else "run_blocked",
        error_desc="" if status == "completed" else (derive_block_reason(spec_path) or f"Spec {spec_id} marked blocked"),
        error_root_cause="",
        error_suggestion="",
    )

    metrics = build_metrics(ns, git, cfg)
    metrics["resolution"] = derive_resolution(
        repo,
        spec_id,
        args.mark_commit,
        in_progress_sha,
        outcome,
    )
    date = completed_at[:10] if len(completed_at) >= 10 else "0000-00-00"

    if args.dry_run:
        print(yaml.safe_dump(metrics, sort_keys=False))
        if status != "completed":
            print(f"[dry-run] would append failure-ledger entry for {spec_id}", file=sys.stderr)
        return 0

    metrics_dir.mkdir(parents=True, exist_ok=True)
    seq = next_sequence(metrics_dir, date)
    out_path = metrics_dir / f"{date}_{seq}_{spec_id}.yaml"
    out_path.write_text(yaml.safe_dump(metrics, sort_keys=False))
    print(f"[mark-commit] wrote {out_path}")
    if status != "completed":
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        append_failure_ledger(metrics_dir / "failure-ledger.json", ns, now, dry_run=False)
        print(f"[mark-commit] appended failure-ledger entry for {spec_id}")
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Emit one schema-valid Nightshift metrics file.")
    p.add_argument("--spec-id", required=True)
    p.add_argument("--spec-file", required=True)
    p.add_argument(
        "--status",
        required=True,
        # SPEC-130: aliases accepted here are normalized to STATUS_ENUM at emission
        choices=sorted(STATUS_ENUM | set(STATUS_ALIASES)),
    )
    p.add_argument("--outcome", required=True, choices=sorted(OUTCOME_ENUM))
    p.add_argument("--started-at", required=True)
    p.add_argument("--completed-at", required=True)
    p.add_argument("--tests-total", type=int, default=0)
    p.add_argument("--tests-passed", type=int, default=0)
    p.add_argument("--lint-errors", type=int, default=0)
    p.add_argument("--type-errors", type=int, default=0)
    p.add_argument("--build-pass", default="true", choices=["true", "false"])
    p.add_argument("--review-cycles", type=int, default=1)
    p.add_argument("--completion-score", type=float, default=1.0)
    p.add_argument("--files-read", type=int, default=0)
    p.add_argument("--knowledge-used", type=int, default=0)
    p.add_argument("--patterns-written", type=int, default=0)
    p.add_argument("--patterns-injected", type=int, default=0)
    p.add_argument("--patterns-cited", type=int, default=0)
    p.add_argument("--model", default="", help="Override config runtime.model (the model running the loop)")
    p.add_argument("--harness", default="", help="Override config runtime.harness")
    p.add_argument("--domain", default="code")
    p.add_argument("--execution-mode", default="sequential")
    p.add_argument("--error-phase", default="")
    p.add_argument("--error-type", default="")
    p.add_argument("--error-desc", default="")
    p.add_argument("--error-root-cause", default="")
    p.add_argument("--error-suggestion", default="")
    p.add_argument("--metrics-dir", default=".nightshift/metrics")
    p.add_argument("--config", default=".nightshift/config.yaml")
    p.add_argument("--repo", default=".")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--mark-commit" in argv:
        return main_mark_commit(argv)

    args = parse_args(argv)
    args.build_pass = args.build_pass == "true"
    # SPEC-130: normalize once at entry; build_metrics picks up status_raw.
    args.status, args.status_raw = normalize_status(args.status)

    if args.status != "completed" and not (args.error_type and args.error_desc):
        print(
            f"Error: status '{args.status}' requires --error-type and --error-desc "
            "(the failure path must be recorded, not invisible).",
            file=sys.stderr,
        )
        return 2

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date = args.completed_at[:10] if len(args.completed_at) >= 10 else "0000-00-00"

    git = derive_git(Path(args.repo))
    cfg = derive_config(Path(args.config), model_override=args.model, harness_override=args.harness)
    metrics = build_metrics(args, git, cfg)

    metrics_dir = Path(args.metrics_dir)
    seq = next_sequence(metrics_dir, date)
    out_path = metrics_dir / f"{date}_{seq}_{args.spec_id}.yaml"

    if args.dry_run:
        print(yaml.safe_dump(metrics, sort_keys=False))
    else:
        metrics_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(yaml.safe_dump(metrics, sort_keys=False))
        print(f"Wrote {out_path}")

    if args.status != "completed":
        append_failure_ledger(metrics_dir / "failure-ledger.json", args, now, args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
