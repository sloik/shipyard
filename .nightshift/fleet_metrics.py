#!/usr/bin/env python3
"""Bounded, local-only aggregation of registered Nightshift metric stores.

The registry is deliberately small and explicit: ``{"projects": [{"id": ..., "path": ...}]}``.
Only the controlled metrics fields below cross the project boundary; raw YAML,
failure text, logs, and project configuration stay in the owning project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from path_vars import ResolutionError, resolve

SNAPSHOT_SCHEMA_VERSION = 1
MAX_WORKERS = 4
SAFE_OUTCOMES = {"done", "partial", "blocked", "noop", "completed", "failed", "discarded"}
OUTCOME_ALIASES = {
    "complete": "done",
    "completed": "done",
    "implemented": "done",
    "pass": "done",
    "passed": "done",
    "success": "done",
}
SAFE_FAILURE_CATEGORIES = {"test_failure", "test_hang", "build_broken", "build_error", "type_error", "lint_error", "timeout", "validation_failure", "rerun_failed", "migration_failed", "managed_copy_conflict", "extension_gap"}
SAFE_BLOCKER_CLASSES = {
    "implementation",
    "test_infrastructure",
    "fixture_drift",
    "baseline_regression",
    "external_input",
    "evidence_gap",
    "scope_violation",
    "unknown",
}
EXPERIMENT_STATES = {"registered", "collecting", "review_due", "resolved", "retired"}
EXPERIMENT_SAMPLE_STATES = {
    "no_samples", "insufficient_samples", "sampled", "censored", "incomplete",
    "instrumentation_gap", "invalidated",
}
EXPERIMENT_CONCLUSIONS = {"supported", "not_supported", "inconclusive", "invalidated", None}
EXPERIMENT_SCOPES = {"none", "single_observation", "repeated_single_project", "cross_project"}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: Any) -> str | None:
    value = str(value or "").strip()
    return value if value.endswith("Z") and "T" in value else None


def _metric_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Return an allowlisted summary; never copy untrusted strings from metrics."""
    phases = data.get("phases") if isinstance(data.get("phases"), dict) else {}
    validation = phases.get("validation") if isinstance(phases.get("validation"), dict) else {}
    failure = data.get("failure") if isinstance(data.get("failure"), dict) else {}
    resolution = data.get("resolution") if isinstance(data.get("resolution"), dict) else {}
    outcome = str(data.get("outcome") or data.get("status") or "").lower()
    outcome = OUTCOME_ALIASES.get(outcome, outcome)
    error_type = str(failure.get("error_type") or "").lower()
    declared_category = str(failure.get("category") or "").lower()
    blocker_class = str(resolution.get("blocker_class") or "").lower()
    failure_category = (
        declared_category if declared_category in SAFE_FAILURE_CATEGORIES | SAFE_BLOCKER_CLASSES
        else error_type if error_type in SAFE_FAILURE_CATEGORIES
        else blocker_class if blocker_class in SAFE_BLOCKER_CLASSES
        else None
    )
    return {
        "outcome": outcome if outcome in SAFE_OUTCOMES else "unknown",
        "failure_category": failure_category,
        "started_at": _iso(data.get("started_at")),
        "completed_at": _iso(data.get("completed_at")),
        "duration_s": int(validation.get("duration_s") or 0) if isinstance(validation.get("duration_s"), (int, float)) else 0,
        "validation_passed": validation.get("build_pass") is True and validation.get("test_pass_rate", 1) >= 1,
        "rerun": bool((data.get("resolution") or {}).get("attempt", 1) > 1) if isinstance(data.get("resolution"), dict) else False,
    }


def experiment_projection_rows(value: Any) -> list[dict[str, Any]]:
    """Read only the documented projection allowlist; never raw observations."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return []
    experiments = value.get("experiments")
    if not isinstance(experiments, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in experiments:
        if not isinstance(item, dict):
            continue
        experiment_id = item.get("experiment_id")
        source_spec_id = item.get("source_spec_id")
        revision = item.get("hypothesis_revision")
        if (
            not isinstance(experiment_id, str) or not experiment_id.startswith("EXP-")
            or not isinstance(source_spec_id, str) or not source_spec_id.startswith("SPEC-")
            or not isinstance(revision, str) or len(revision) != 64
            or item.get("state") not in EXPERIMENT_STATES
            or item.get("sample_state") not in EXPERIMENT_SAMPLE_STATES
            or item.get("conclusion") not in EXPERIMENT_CONCLUSIONS
            or item.get("evidence_scope") not in EXPERIMENT_SCOPES
        ):
            continue
        eligible = item.get("eligible")
        numerator = item.get("numerator")
        denominator = item.get("denominator")
        value_number = item.get("value")
        if any(isinstance(number, bool) or not isinstance(number, int) or number < 0 for number in (eligible, numerator, denominator)):
            continue
        if value_number is not None and (isinstance(value_number, bool) or not isinstance(value_number, (int, float))):
            continue
        rows.append({
            "experiment_id": experiment_id,
            "source_spec_id": source_spec_id,
            "hypothesis_revision": revision,
            "state": item["state"],
            "review_trigger": item.get("review_trigger") if item.get("review_trigger") == "first_of_minimum_or_deadline" else None,
            "sample_state": item["sample_state"],
            "eligible": eligible,
            "numerator": numerator,
            "denominator": denominator,
            "value": value_number,
            "evidence_scope": item["evidence_scope"],
            "conclusion": item["conclusion"],
            "time_to_first_evidence_s": item.get("time_to_first_evidence_s") if isinstance(item.get("time_to_first_evidence_s"), int) else None,
        })
    return sorted(rows, key=lambda row: (row["experiment_id"], row["hypothesis_revision"]))


def _read_project(project: dict[str, Any]) -> dict[str, Any]:
    project_id, raw_path = project.get("id"), project.get("path")
    if not isinstance(project_id, str) or not isinstance(raw_path, str):
        return {"error": "invalid_registry_entry", "project": str(project_id or "unknown")}
    if project.get("_resolution_error"):
        return {"error": "unresolvable_path", "project": project_id, "path": raw_path}
    root = Path(str(project.get("_resolved_path") or raw_path)).expanduser()
    metric_root = root if (root / "metrics").is_dir() else root / ".nightshift"
    metrics = metric_root / "metrics"
    if not metrics.is_dir():
        return {"error": "unreachable", "project": project_id, "path": raw_path}
    files = sorted(metrics.glob("*.yaml")) + sorted(metrics.glob("*.yml"))
    rows = []
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            rows.append({"source_hash": _hash(path), **_metric_summary(data)})
    experiment_rows: list[dict[str, Any]] = []
    experiment_path = metric_root / "reports" / "_wip" / "experiment-status.json"
    if experiment_path.is_file() and not experiment_path.is_symlink():
        try:
            experiment_rows = experiment_projection_rows(json.loads(experiment_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            experiment_rows = []
    marker = metric_root / "release-marker.json"
    provenance = {
        "project": project_id,
        "path": raw_path,
        "metric_files": len(rows),
        "metric_hashes": sorted(row["source_hash"] for row in rows),
    }
    if isinstance(project.get("expected_release_fingerprint"), str):
        provenance["expected_release_fingerprint"] = project["expected_release_fingerprint"]
    if marker.is_file():
        try:
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            manifest = marker_data.get("release_manifest") if isinstance(marker_data.get("release_manifest"), dict) else {}
            values = {
                "kit_version": marker_data.get("kit_version"),
                "release_fingerprint": marker_data.get("fingerprint"),
                "schema_version": marker_data.get("schema_version") or manifest.get("schema_version"),
            }
            for key, value in values.items():
                if isinstance(value, (str, int, float)):
                    provenance[key] = value
        except (OSError, json.JSONDecodeError):
            pass
    else:
        manifest_path = metric_root / "release-manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                values = {
                    "kit_version": manifest.get("kit_version"),
                    "release_fingerprint": manifest.get("fingerprint"),
                    "schema_version": manifest.get("schema_version"),
                }
                for key, value in values.items():
                    if isinstance(value, (str, int, float)):
                        provenance[key] = value
            except (OSError, json.JSONDecodeError):
                pass
    return {"project": provenance, "rows": rows, "experiments": experiment_rows}


def _scope(rows: list[dict[str, Any]]) -> str:
    projects = {row["project"] for row in rows}
    return "single_observation" if len(rows) == 1 else "repeated_single_project" if len(projects) == 1 else "cross_project"


def normalize_project_results(results: list[dict[str, Any]], registered: int, *, collected_at: str | None = None) -> dict[str, Any]:
    """Create deterministic evidence fields from bounded project results."""
    reachable = [item for item in results if "rows" in item]
    missing = [{"project": item.get("project"), "reason": item.get("error")} for item in results if "error" in item]
    projects = []
    for item in reachable:
        projects.append(item["project"])
    # Group by category after preserving source project separately.
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in reachable:
        for row in item["rows"]:
            grouped[str(row.get("failure_category") or row.get("outcome"))].append({**row, "project": item["project"]["project"]})
    evidence = []
    for category, rows in sorted(grouped.items()):
        timestamps = sorted(value for row in rows for value in (row.get("started_at"), row.get("completed_at")) if value)
        evidence.append({
            "category": category,
            "scope": _scope(rows),
            "distinct_projects": sorted({row["project"] for row in rows}),
            "observation_count": len(rows),
            "eligible_runs": sum(project["metric_files"] for project in projects),
            "first_seen": timestamps[0] if timestamps else None,
            "last_seen": timestamps[-1] if timestamps else None,
            "elapsed_s": 0 if len(timestamps) < 2 else int((datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00")) - datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))).total_seconds()),
        })
    exact_version_drift = [
        project["project"] for project in projects
        if project.get("expected_release_fingerprint") and project.get("release_fingerprint") != project["expected_release_fingerprint"]
    ]
    all_rows = [row for item in reachable for row in item["rows"]]
    unknown_outcomes = sum(row.get("outcome") == "unknown" for row in all_rows)
    blocked_rows = [row for row in all_rows if row.get("outcome") == "blocked"]
    classified_blocked = sum(
        bool(row.get("failure_category")) and row.get("failure_category") != "unknown"
        for row in blocked_rows
    )
    experiment_rows = [
        {**row, "project": item["project"]["project"]}
        for item in reachable for row in item.get("experiments", [])
    ]

    def quality_metric(numerator: int, denominator: int) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "eligible_denominator": denominator,
            "value": round(numerator / denominator * 100, 1) if denominator else None,
        }

    registered_experiments = len(experiment_rows)
    review_population = sum(row["state"] in {"review_due", "resolved"} for row in experiment_rows)
    impactful = sum(row["conclusion"] in {"not_supported", "invalidated"} for row in experiment_rows)
    experiment_metrics = {
        "states": dict(sorted(Counter(row["state"] for row in experiment_rows).items())),
        "conclusions": dict(sorted(Counter(row["conclusion"] for row in experiment_rows if row["conclusion"] is not None).items())),
        "evidence_scopes": dict(sorted(Counter(row["evidence_scope"] for row in experiment_rows).items())),
        "instrumentation_coverage_rate": quality_metric(sum(row["eligible"] > 0 for row in experiment_rows), registered_experiments),
        "no_sample_experiment_rate": quality_metric(sum(row["sample_state"] == "no_samples" for row in experiment_rows if row["state"] in {"review_due", "resolved"}), review_population),
        "review_overdue_rate": quality_metric(sum(row["state"] == "review_due" for row in experiment_rows), review_population),
        "impactful_conclusions": impactful,
        "time_to_first_evidence_s": [row["time_to_first_evidence_s"] for row in experiment_rows if row["time_to_first_evidence_s"] is not None],
    }

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        # A supplied collection timestamp is retained for auditability.  The
        # default derives from source windows so identical inputs stay identical.
        "collected_at": collected_at or max((row.get("completed_at") or row.get("started_at") or "" for item in reachable for row in item["rows"]), default=None),
        "denominators": {"registered_projects": registered, "reachable_projects": len(reachable), "missing_projects": len(missing), "eligible_runs": sum(project["metric_files"] for project in projects)},
        "missing_projects": missing,
        "projects": sorted(projects, key=lambda item: item["project"]),
        "observations": evidence,
        "outcomes": dict(sorted(Counter(row.get("outcome") for item in reachable for row in item["rows"]).items())),
        "evidence_quality": {
            "fleet_unknown_outcome_rate": quality_metric(unknown_outcomes, len(all_rows)),
            "fleet_blocked_classification_rate": quality_metric(classified_blocked, len(blocked_rows)),
        },
        "collection_failures": len(missing),
        "release_coverage": {
            "projects_with_release_fingerprint": sum("release_fingerprint" in project for project in projects),
            "exact_version_drift_projects": sorted(exact_version_drift),
        },
        "experiments": {
            "registered": registered_experiments,
            "metrics": experiment_metrics,
            "rows": experiment_rows,
        },
    }


def write_snapshot(snapshot: dict[str, Any], output: Path) -> Path:
    """Atomically replace the sole gitignored WIP snapshot."""
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return output


def collect_fleet_metrics(registry: Path, output: Path, *, workers: int = MAX_WORKERS) -> dict[str, Any]:
    data = json.loads(registry.read_text(encoding="utf-8"))
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, list): raise ValueError("registry must contain a projects list")
    names = Counter(
        project.get("id") or project.get("name")
        for project in projects
        if isinstance(project, dict) and isinstance(project.get("id") or project.get("name"), str)
    )
    anchor_root = registry.parent.parent if registry.parent.name == ".nightshift" else registry.parent
    prepared = []
    for project in projects:
        if not isinstance(project, dict):
            prepared.append({})
            continue
        item = dict(project)
        identity = item.get("id") or item.get("name")
        raw_path = item.get("path")
        if isinstance(identity, str) and isinstance(raw_path, str):
            item["id"] = f"{identity}@{raw_path}" if names[identity] > 1 else identity
            try:
                item["_resolved_path"] = resolve(raw_path, anchor_root, mode="execute")
            except ResolutionError:
                item["_resolution_error"] = True
        prepared.append(item)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, MAX_WORKERS, len(projects) or 1))) as pool:
        results = list(pool.map(_read_project, prepared))
    snapshot = normalize_project_results(results, len(projects))
    write_snapshot(snapshot, output)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect bounded Nightshift fleet metrics")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/_wip/fleet-metrics-snapshot.json"))
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    snapshot = collect_fleet_metrics(args.registry, args.output, workers=args.workers)
    print(json.dumps({"snapshot": str(args.output), "denominators": snapshot["denominators"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
