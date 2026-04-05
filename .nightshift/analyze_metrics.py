#!/usr/bin/env python3
"""
Cross-Run Metrics Analyzer for Nightshift

Aggregates per-spec YAML metrics across runs to identify trends, phase bottlenecks,
model performance differences, and regression alerts.

Usage:
    python3 analyze_metrics.py <metrics_dir> [--since YYYY-MM-DD] [--compare-models]

Exit codes:
    0 — Analysis complete, no regressions
    2 — Analysis complete, regression alerts generated
"""

import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# Import validate_metrics for input validation
try:
    from validate_metrics import validate_file
except ImportError:
    print("Error: validate_metrics.py not found or not importable", file=sys.stderr)
    sys.exit(1)

try:
    from failure_persistence import persist_failure, normalize_status
except ImportError:
    print("Error: failure_persistence.py not found or not importable", file=sys.stderr)
    sys.exit(1)


# Exit codes
EXIT_SUCCESS = 0
EXIT_REGRESSION_DETECTED = 2

# Regression thresholds (from SPEC-002 R6)
THRESHOLDS = {
    "test_pass_rate_drop_pct": 10,  # >10% drop vs 5-run average
    "review_cycles_increase_pct": 50,  # >50% increase vs 5-run average
    "phase_duration_multiplier": 2.0,  # >2x its 5-run average
    "pattern_citation_rate_drop_pct": 30,  # >30% drop vs 5-run average
    "gap_report_frequency_pct": 30,  # >30% of specs
    "circuit_breaker_frequency_pct": 20,  # >20% of specs
}

# Default lookback for trend analysis
DEFAULT_LOOKBACK = 10
DEFAULT_REGRESSION_LOOKBACK = 5
GAP_RESOLUTIONS = {"pending", "spec_updated", "work_dropped"}


def _coerce_int(value: Any, default: int = 0) -> int:
    """Coerce unknown numeric-like values to int safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (TypeError, ValueError):
            return default
    return default


def _extract_frontmatter(markdown_text: str) -> Dict[str, Any]:
    """
    Extract YAML frontmatter from markdown text.

    Returns empty dict when frontmatter is absent or malformed.
    """
    if not markdown_text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", markdown_text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except Exception:
        return {}
    return frontmatter if isinstance(frontmatter, dict) else {}


def _normalize_resolution(value: Any) -> str:
    """Normalize gap resolution status to known enum."""
    normalized = str(value or "pending").strip().lower()
    return normalized if normalized in GAP_RESOLUTIONS else "pending"


def _build_gap_key(report: Dict[str, Any]) -> Tuple[str, str]:
    """Build stable merge key for gap report records."""
    return (
        str(report.get("spec_id") or "").strip(),
        str(report.get("timestamp") or "").strip(),
    )


def _load_gap_report_markdown(report_path: Path) -> Optional[Dict[str, Any]]:
    """Load one GAP-*.md report by parsing YAML frontmatter."""
    try:
        content = report_path.read_text(encoding="utf-8")
    except Exception:
        return None
    meta = _extract_frontmatter(content)
    if not meta:
        return None

    return {
        "spec_id": meta.get("spec_id"),
        "gap_type": meta.get("gap_type", "unknown"),
        "phase_stopped": _coerce_int(meta.get("phase_stopped")),
        "research_attempts": _coerce_int(meta.get("research_attempts")),
        "time_before_stop_s": _coerce_int(meta.get("time_before_stop_s")),
        "tokens_before_stop": _coerce_int(meta.get("tokens_before_stop")),
        "root_cause_category": meta.get("root_cause_category", "unknown"),
        "specific_gap": meta.get("specific_gap", ""),
        "resolution": _normalize_resolution(meta.get("resolution")),
        "timestamp": meta.get("timestamp"),
        "source_file": str(report_path.name),
    }


def _load_gap_report_yaml(yaml_path: Path) -> Optional[Dict[str, Any]]:
    """Load one gap report YAML from metrics/gaps or reports."""
    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    return {
        "spec_id": data.get("spec_id"),
        "gap_type": data.get("gap_type", "unknown"),
        "phase_stopped": _coerce_int(data.get("phase_stopped")),
        "research_attempts": _coerce_int(data.get("research_attempts")),
        "time_before_stop_s": _coerce_int(data.get("time_before_stop_s")),
        "tokens_before_stop": _coerce_int(data.get("tokens_before_stop")),
        "root_cause_category": data.get("root_cause_category", "unknown"),
        "specific_gap": data.get("specific_gap", data.get("summary", "")),
        "resolution": _normalize_resolution(data.get("resolution")),
        "timestamp": data.get("timestamp"),
        "source_file": str(yaml_path.name),
    }


def load_gap_reports(metrics_dir_path):
    """
    Load and merge gap reports from:
    - .nightshift/reports/GAP-*.md (frontmatter)
    - .nightshift/metrics/gaps/*-gap.yaml (companion metrics)
    - .nightshift/reports/GAP-*.yaml (legacy fallback)

    Companion YAML values override markdown fields when present.
    """
    metrics_dir = Path(metrics_dir_path)
    project_root = metrics_dir.parent
    reports_dir = project_root / "reports"
    gaps_metrics_dir = metrics_dir / "gaps"

    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}

    md_files = sorted(reports_dir.glob("GAP-*.md")) if reports_dir.is_dir() else []
    for md_file in md_files:
        record = _load_gap_report_markdown(md_file)
        if not record:
            continue
        key = _build_gap_key(record)
        merged[key] = record

    yaml_files = []
    if gaps_metrics_dir.is_dir():
        yaml_files.extend(sorted(gaps_metrics_dir.glob("*.yaml")))
        yaml_files.extend(sorted(gaps_metrics_dir.glob("*.yml")))
    if reports_dir.is_dir():
        yaml_files.extend(sorted(reports_dir.glob("GAP-*.yaml")))
        yaml_files.extend(sorted(reports_dir.glob("GAP-*.yml")))

    for yaml_file in yaml_files:
        record = _load_gap_report_yaml(yaml_file)
        if not record:
            continue
        key = _build_gap_key(record)
        existing = merged.get(key, {})
        merged[key] = {**existing, **{k: v for k, v in record.items() if v not in ("", None)}}
        merged[key]["source_file"] = str(yaml_file.name)

    reports = list(merged.values())
    reports.sort(key=lambda r: _parse_iso8601(r.get("timestamp")))
    return reports


def _infer_requirement_pattern(report: Dict[str, Any]) -> str:
    """Infer rough requirement-pattern bucket from root cause and gap text."""
    root = str(report.get("root_cause_category", "")).lower()
    text = " ".join(
        str(report.get(k, "")).lower()
        for k in ("specific_gap",)
    )
    haystack = f"{root} {text}"

    if "ambiguous" in haystack or "unclear" in haystack:
        return "ambiguous_requirement"
    if "acceptance" in haystack or "ac-" in haystack:
        return "missing_acceptance_criteria"
    if "edge case" in haystack or "edge-case" in haystack:
        return "missing_edge_cases"
    if "api contract" in haystack or ("api" in haystack and "format" in haystack):
        return "missing_api_contract"
    if "performance" in haystack or "latency" in haystack or "fast" in haystack:
        return "missing_performance_target"
    if "contradict" in haystack or "conflict" in haystack:
        return "contradictory_requirements"
    if "dependency" in haystack or "after:" in haystack:
        return "missing_dependencies"
    if root in {"missing_context", "missing_domain", "tooling_unknown"}:
        return root
    return "other"


def compute_gap_analytics(gap_reports):
    """
    Aggregate gap report analytics for Phase 5.

    Returns a normalized analytics payload used by markdown and status outputs.
    """
    total = len(gap_reports)
    if total == 0:
        return {
            "total_gaps": 0,
            "by_gap_type": {},
            "by_root_cause": {},
            "by_phase": {},
            "by_resolution": {},
            "resolution_over_time": {},
            "by_requirement_pattern": {},
            "total_time_before_stop_s": 0,
            "total_tokens_before_stop": 0,
            "top_gap_type": None,
            "top_root_cause": None,
            "top_requirement_pattern": None,
            "recommendations": [
                "No historical gaps found. Keep collecting GAP reports and companion metrics/gaps YAML files."
            ],
        }

    by_gap_type = Counter()
    by_root_cause = Counter()
    by_phase = Counter()
    by_resolution = Counter()
    by_requirement_pattern = Counter()
    resolution_over_time = defaultdict(lambda: Counter())
    total_time = 0
    total_tokens = 0

    for report in gap_reports:
        gap_type = str(report.get("gap_type") or "unknown")
        root_cause = str(report.get("root_cause_category") or "unknown")
        phase = _coerce_int(report.get("phase_stopped"), default=0)
        resolution = _normalize_resolution(report.get("resolution"))
        pattern = _infer_requirement_pattern(report)

        by_gap_type[gap_type] += 1
        by_root_cause[root_cause] += 1
        by_phase[str(phase)] += 1
        by_resolution[resolution] += 1
        by_requirement_pattern[pattern] += 1

        ts = _parse_iso8601(report.get("timestamp"))
        day = ts.date().isoformat() if ts != datetime.min else "unknown"
        resolution_over_time[day][resolution] += 1

        total_time += _coerce_int(report.get("time_before_stop_s"))
        total_tokens += _coerce_int(report.get("tokens_before_stop"))

    recommendations = []
    top_root_cause = by_root_cause.most_common(1)[0][0] if by_root_cause else None
    top_pattern = by_requirement_pattern.most_common(1)[0][0] if by_requirement_pattern else None
    top_phase = by_phase.most_common(1)[0][0] if by_phase else None

    if top_root_cause == "ambiguous_requirement":
        recommendations.append(
            "Strengthen /nightshift spec interview prompts for measurable requirements and explicit edge-case definitions."
        )
    if top_pattern == "missing_acceptance_criteria":
        recommendations.append(
            "Enforce requirement-to-AC mapping in spec review and reject specs with non-testable acceptance criteria."
        )
    if top_phase in {"7", "8", "9"}:
        recommendations.append(
            f"Most gaps stop late (phase {top_phase}); add earlier ambiguity checks in spec interview to fail fast."
        )
    pending_rate = by_resolution.get("pending", 0) / total
    if pending_rate > 0.5:
        recommendations.append(
            "Pending resolution backlog is high; add a routine to review and close gap reports before new spec batches."
        )
    if not recommendations:
        recommendations.append(
            "Continue collecting gap data and review template sections with highest gap concentration."
        )

    return {
        "total_gaps": total,
        "by_gap_type": dict(by_gap_type),
        "by_root_cause": dict(by_root_cause),
        "by_phase": dict(by_phase),
        "by_resolution": dict(by_resolution),
        "resolution_over_time": {day: dict(counter) for day, counter in sorted(resolution_over_time.items())},
        "by_requirement_pattern": dict(by_requirement_pattern),
        "total_time_before_stop_s": total_time,
        "total_tokens_before_stop": total_tokens,
        "top_gap_type": by_gap_type.most_common(1)[0][0] if by_gap_type else None,
        "top_root_cause": top_root_cause,
        "top_requirement_pattern": top_pattern,
        "recommendations": recommendations,
    }


def generate_gap_analytics_markdown(analytics):
    """Render GAP-ANALYTICS.md content."""
    lines = [
        "# GAP ANALYTICS",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "## Overview",
        "",
        f"- Total gaps analyzed: {analytics.get('total_gaps', 0)}",
        f"- Total time before stop (wasted): {analytics.get('total_time_before_stop_s', 0)}s",
        f"- Total tokens before stop (wasted): {analytics.get('total_tokens_before_stop', 0)}",
        "",
        "## Gap Frequency by Type",
        "",
    ]

    by_type = analytics.get("by_gap_type", {})
    if by_type:
        for gap_type, count in sorted(by_type.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"- {gap_type}: {count}")
    else:
        lines.append("- No gap reports found.")

    lines.extend(["", "## Top Root Causes", ""])
    by_root = analytics.get("by_root_cause", {})
    if by_root:
        for cause, count in sorted(by_root.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            lines.append(f"- {cause}: {count}")
    else:
        lines.append("- No root cause data.")

    lines.extend(["", "## Requirement Patterns Producing Gaps", ""])
    by_req = analytics.get("by_requirement_pattern", {})
    if by_req:
        for pattern, count in sorted(by_req.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            lines.append(f"- {pattern}: {count}")
    else:
        lines.append("- No requirement-pattern data.")

    lines.extend(["", "## Resolution Rate", ""])
    by_res = analytics.get("by_resolution", {})
    total = analytics.get("total_gaps", 0) or 1
    for resolution in ("pending", "spec_updated", "work_dropped"):
        count = by_res.get(resolution, 0)
        lines.append(f"- {resolution}: {count} ({(count / total) * 100:.1f}%)")

    lines.extend(["", "## Resolution Trend Over Time", ""])
    trend = analytics.get("resolution_over_time", {})
    if trend:
        for day, counts in trend.items():
            lines.append(
                f"- {day}: pending={counts.get('pending', 0)}, "
                f"spec_updated={counts.get('spec_updated', 0)}, "
                f"work_dropped={counts.get('work_dropped', 0)}"
            )
    else:
        lines.append("- No dated resolution data.")

    lines.extend(["", "## Phase Distribution", ""])
    by_phase = analytics.get("by_phase", {})
    if by_phase:
        for phase, count in sorted(by_phase.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"- Phase {phase}: {count}")
    else:
        lines.append("- No phase distribution data.")

    lines.extend(["", "## Recommendations", ""])
    for rec in analytics.get("recommendations", []):
        lines.append(f"- {rec}")

    return "\n".join(lines)


def write_gap_analytics_report(analytics, reports_dir_path):
    """Write GAP-ANALYTICS.md to reports directory."""
    reports_dir = Path(reports_dir_path)
    reports_dir.mkdir(parents=True, exist_ok=True)
    target = reports_dir / "GAP-ANALYTICS.md"
    target.write_text(generate_gap_analytics_markdown(analytics))
    return target


def write_gap_analytics_status_snapshot(analytics, reports_dir_path):
    """
    Write machine-readable gap status for `/nightshift spec` interview warnings.

    The interview flow can read this file to show top recurring gap risks before
    eliciting requirements.
    """
    reports_dir = Path(reports_dir_path)
    reports_dir.mkdir(parents=True, exist_ok=True)
    status_file = reports_dir / "GAP-ANALYTICS-STATUS.json"

    total = analytics.get("total_gaps", 0) or 0
    by_root = analytics.get("by_root_cause", {}) or {}
    top_root_cause = analytics.get("top_root_cause")
    warnings = []

    if top_root_cause == "ambiguous_requirement" and total > 0:
        count = by_root.get("ambiguous_requirement", 0)
        warnings.append({
            "code": "AMBIGUOUS_REQUIREMENT",
            "message": (
                "Top recurring gap root cause is ambiguous_requirement. "
                "Define explicit edge cases, measurable constraints, and testable ACs."
            ),
            "count": count,
            "share_pct": round((count / total) * 100, 1),
        })

    pending = (analytics.get("by_resolution", {}) or {}).get("pending", 0)
    if total > 0 and pending / total > 0.5:
        warnings.append({
            "code": "HIGH_PENDING_GAP_BACKLOG",
            "message": "More than 50% of historical gaps are still pending resolution.",
            "count": pending,
            "share_pct": round((pending / total) * 100, 1),
        })

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_gaps": total,
        "top_gap_type": analytics.get("top_gap_type"),
        "top_root_cause": top_root_cause,
        "top_requirement_pattern": analytics.get("top_requirement_pattern"),
        "warnings": warnings,
    }
    status_file.write_text(json.dumps(payload, indent=2, default=str))
    return status_file


def _parse_iso8601(value: Optional[str]) -> datetime:
    """Best-effort ISO timestamp parsing with deterministic fallback."""
    if not value:
        return datetime.min
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.min


def load_metrics_files(metrics_dir_path):
    """
    Load all valid metrics YAML files from directory.

    Validates each file via validate_metrics.validate_file(). Skips invalid files
    with a warning. Returns sorted list by filename.

    Args:
        metrics_dir_path (str): Path to metrics directory

    Returns:
        list[dict]: Validated metrics data, sorted by filename
    """
    metrics_dir = Path(metrics_dir_path)

    if not metrics_dir.is_dir():
        print(f"Error: {metrics_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    yaml_files = sorted(metrics_dir.glob("*.yaml")) + sorted(metrics_dir.glob("*.yml"))

    loaded_metrics = []
    project_root = metrics_dir.parent

    for yaml_file in yaml_files:
        # Load raw content first so we can persist detailed fallback failures
        try:
            with open(yaml_file, "r") as f:
                raw_data = yaml.safe_load(f)
        except Exception as e:
            persist_failure(
                project_root=project_root,
                source_file=str(yaml_file.name),
                error_type="metrics_load_error",
                description=f"Failed to parse YAML: {e}",
                details={"path": str(yaml_file)},
            )
            print(f"Warning: Failed to load {yaml_file.name}: {e}", file=sys.stderr)
            continue

        if not isinstance(raw_data, dict):
            persist_failure(
                project_root=project_root,
                source_file=str(yaml_file.name),
                error_type="metrics_invalid_root",
                description="Metrics file root is not a dictionary.",
                details={"path": str(yaml_file)},
            )
            print(f"Warning: Skipping invalid file {yaml_file.name}: root must be dict", file=sys.stderr)
            continue

        raw_status = raw_data.get("status")
        normalized_status, legacy_raw = normalize_status(raw_status)
        if legacy_raw:
            raw_data["raw_status"] = legacy_raw
            raw_data["status"] = normalized_status
            # Write normalized metrics file back atomically to prevent recurring alias issues.
            fd, tmp_path = tempfile.mkstemp(prefix=f".{yaml_file.name}.", dir=str(yaml_file.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    yaml.safe_dump(raw_data, f, sort_keys=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, yaml_file)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        # Unknown statuses must be persisted as durable failures (not warnings only).
        known_statuses = {"completed", "failed", "blocked", "discarded", "partial"}
        if raw_data.get("status") not in known_statuses:
            persist_failure(
                project_root=project_root,
                source_file=str(yaml_file.name),
                error_type="status_unrecognized",
                description=f"Unknown metrics status: {raw_data.get('status')}",
                details={"path": str(yaml_file), "raw_status": raw_status},
                spec_file=raw_data.get("spec_file"),
                status="failed",
                raw_status=raw_status if isinstance(raw_status, str) else None,
            )
            print(
                f"Warning: Persisted failure for unknown status in {yaml_file.name}: {raw_data.get('status')}",
                file=sys.stderr,
            )
            continue

        # Validate before loading
        errors = validate_file(yaml_file)
        if errors:
            error_type = "status_unrecognized" if "status' must be one of" in errors[0] else "metrics_validation_failed"
            persist_failure(
                project_root=project_root,
                source_file=str(yaml_file.name),
                error_type=error_type,
                description=errors[0],
                details={"path": str(yaml_file), "validation_errors": errors},
                spec_file=raw_data.get("spec_file"),
                status="failed",
                raw_status=raw_status if isinstance(raw_status, str) else None,
            )
            print(f"Warning: Skipping invalid file {yaml_file.name}: {errors[0]}", file=sys.stderr)
            continue

        try:
            with open(yaml_file, "r") as f:
                data = yaml.safe_load(f)
            loaded_metrics.append(data)
        except Exception as e:
            persist_failure(
                project_root=project_root,
                source_file=str(yaml_file.name),
                error_type="metrics_load_error",
                description=f"Failed loading validated file: {e}",
                details={"path": str(yaml_file)},
            )
            print(f"Warning: Failed to load {yaml_file.name}: {e}", file=sys.stderr)
            continue

    loaded_metrics.sort(key=lambda m: _parse_iso8601(m.get("started_at")))
    return loaded_metrics


def load_coordinator_metrics(metrics_dir_path):
    """
    Load coordinator metrics files from metrics/coordinator/.

    Args:
        metrics_dir_path (str): Path to .nightshift/metrics directory.

    Returns:
        list[dict]: Coordinator run metrics sorted by started_at.
    """
    coordinator_dir = Path(metrics_dir_path) / "coordinator"
    if not coordinator_dir.is_dir():
        return []

    yaml_files = sorted(coordinator_dir.glob("*.yaml")) + sorted(coordinator_dir.glob("*.yml"))
    loaded = []
    for yaml_file in yaml_files:
        try:
            with open(yaml_file, "r") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                loaded.append(data)
        except Exception:
            continue

    loaded.sort(key=lambda m: _parse_iso8601(m.get("started_at")))
    return loaded


def filter_by_date(metrics, since_datetime):
    """
    Filter metrics to only those after a given date.

    Args:
        metrics (list[dict]): Metrics to filter
        since_datetime (datetime): Only include metrics with started_at >= this date

    Returns:
        list[dict]: Filtered metrics, sorted by started_at
    """
    filtered = []

    for metric in metrics:
        started_at_str = metric.get("started_at")
        if not started_at_str:
            continue

        try:
            # Parse ISO 8601 timestamp
            started_at = datetime.fromisoformat(
                started_at_str.replace("Z", "+00:00")
            )
            # Make since_datetime timezone-aware if it isn't
            since_aware = since_datetime
            if since_aware.tzinfo is None:
                from datetime import timezone
                since_aware = since_aware.replace(tzinfo=timezone.utc)

            if started_at >= since_aware:
                filtered.append(metric)
        except (ValueError, AttributeError):
            continue

    # Sort by started_at
    filtered.sort(key=lambda m: m.get("started_at", ""))
    return filtered


def compute_trends(metrics, lookback=DEFAULT_LOOKBACK):
    """
    Compute trend report showing per-metric trends over the last N runs.

    Tracks: completion rate, average duration, average review cycles,
    average test pass rate, average satisfaction score.

    Args:
        metrics (list[dict]): Metrics to analyze
        lookback (int): Number of recent runs to include in trend

    Returns:
        dict: Trend data with keys like "test_pass_rate", "review_cycles", etc.
              Each trend includes "values", "average", "direction" (↑/↓/→)
    """
    # Take only the last N metrics
    recent = metrics[-lookback:] if len(metrics) > lookback else metrics

    trends = {}

    # Test pass rate trend
    test_pass_rates = []
    for metric in recent:
        val = metric.get("phases", {}).get("validation", {}).get("test_pass_rate")
        if val is not None:
            test_pass_rates.append(val)

    if test_pass_rates:
        trends["test_pass_rate"] = {
            "values": test_pass_rates,
            "average": sum(test_pass_rates) / len(test_pass_rates),
            "direction": _compute_direction(test_pass_rates),
        }

    # Review cycles trend
    review_cycles = []
    for metric in recent:
        val = metric.get("phases", {}).get("review", {}).get("cycles")
        if val is not None:
            review_cycles.append(val)

    if review_cycles:
        trends["review_cycles"] = {
            "values": review_cycles,
            "average": sum(review_cycles) / len(review_cycles),
            "direction": _compute_direction(review_cycles, inverse=True),  # more is worse
        }

    # Average spec duration
    spec_durations = []
    for metric in recent:
        # Sum all phase durations
        phases = metric.get("phases", {})
        duration = 0
        for phase_name, phase_data in phases.items():
            if isinstance(phase_data, dict):
                duration += phase_data.get("duration_s", 0)
        if duration > 0:
            spec_durations.append(duration)

    if spec_durations:
        trends["average_spec_duration_s"] = {
            "values": spec_durations,
            "average": sum(spec_durations) / len(spec_durations),
            "direction": _compute_direction(spec_durations, inverse=True),  # faster is better
        }

    # Overall satisfaction trend
    satisfaction_scores = []
    for metric in recent:
        val = metric.get("satisfaction", {}).get("overall_score")
        if val is not None:
            satisfaction_scores.append(val)

    if satisfaction_scores:
        trends["overall_satisfaction"] = {
            "values": satisfaction_scores,
            "average": sum(satisfaction_scores) / len(satisfaction_scores),
            "direction": _compute_direction(satisfaction_scores),
        }

    # Completion rate (% of completed specs)
    completed = sum(1 for m in recent if m.get("status") == "completed")
    completion_rate = completed / len(recent) if recent else 0
    trends["completion_rate"] = {
        "value": completion_rate,
        "completed": completed,
        "total": len(recent),
    }

    return trends


def _compute_direction(values, inverse=False):
    """
    Compute trend direction based on first-half vs second-half average.

    Args:
        values (list[float]): Values in chronological order
        inverse (bool): If True, higher is worse (↓ means better)

    Returns:
        str: "↑" if improving, "↓" if degrading, "→" if stable
    """
    if len(values) < 2:
        return "→"

    mid = len(values) // 2
    first_half = sum(values[:mid]) / len(values[:mid]) if mid > 0 else values[0]
    second_half = sum(values[mid:]) / len(values[mid:])

    # Determine if improving or degrading
    if inverse:
        # Lower is better
        if second_half < first_half * 0.95:
            return "↓" if inverse else "↑"
        elif second_half > first_half * 1.05:
            return "↑" if inverse else "↓"
    else:
        # Higher is better
        if second_half > first_half * 1.05:
            return "↑"
        elif second_half < first_half * 0.95:
            return "↓"

    return "→"


def compute_phase_breakdown(metrics):
    """
    Compute phase breakdown showing average time per phase, ranked by duration.

    Args:
        metrics (list[dict]): Metrics to analyze

    Returns:
        dict: Phase breakdown with "phases" list ranked by average duration
    """
    phase_durations = {}

    for metric in metrics:
        phases = metric.get("phases", {})
        for phase_name, phase_data in phases.items():
            if phase_name == "execution_mode" or not isinstance(phase_data, dict):
                continue

            duration = phase_data.get("duration_s")
            if duration is None:
                continue

            if phase_name not in phase_durations:
                phase_durations[phase_name] = []

            phase_durations[phase_name].append(duration)

    # Compute averages and rank
    phases_ranked = []
    for phase_name, durations in phase_durations.items():
        avg_duration = sum(durations) / len(durations)
        phases_ranked.append({
            "name": phase_name,
            "average_duration_s": avg_duration,
            "runs": len(durations),
        })

    phases_ranked.sort(key=lambda p: p["average_duration_s"], reverse=True)

    return {
        "phases": phases_ranked,
        "total_average_s": sum(p["average_duration_s"] for p in phases_ranked),
    }


def compute_model_comparison(metrics):
    """
    Compute model comparison showing per-model performance metrics.

    Requires --compare-models flag. Groups by "model" field and compares
    completion rate, average duration, and satisfaction score.

    Args:
        metrics (list[dict]): Metrics to analyze

    Returns:
        dict: Model comparison data, keyed by model name
              Each model entry has "runs", "avg_satisfaction", "avg_duration_s",
              "completion_rate"
    """
    by_model = {}

    for metric in metrics:
        model = metric.get("model", "unknown")

        if model not in by_model:
            by_model[model] = {
                "runs": [],
                "satisfactions": [],
                "durations": [],
                "completed": 0,
            }

        by_model[model]["runs"].append(metric)
        by_model[model]["satisfactions"].append(metric.get("satisfaction", {}).get("overall_score", 0))

        # Total duration
        duration = 0
        for phase_data in metric.get("phases", {}).values():
            if isinstance(phase_data, dict):
                duration += phase_data.get("duration_s", 0)
        by_model[model]["durations"].append(duration)

        if metric.get("status") == "completed":
            by_model[model]["completed"] += 1

    # Compute summary stats
    comparison = {}
    for model, data in by_model.items():
        num_runs = len(data["runs"])
        comparison[model] = {
            "runs": num_runs,
            "avg_satisfaction": sum(data["satisfactions"]) / len(data["satisfactions"]) if data["satisfactions"] else 0,
            "avg_duration_s": sum(data["durations"]) / len(data["durations"]) if data["durations"] else 0,
            "completion_rate": data["completed"] / num_runs if num_runs > 0 else 0,
        }

    return comparison


def _safe_avg(values: List[float]) -> Optional[float]:
    """Return average or None when empty."""
    if not values:
        return None
    return sum(values) / len(values)


def _severity_from_breach_ratio(ratio: float) -> str:
    """Map threshold breach ratio to severity."""
    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.5:
        return "high"
    return "medium"


def _normalize_metric_value(value: Any):
    """Normalize booleans as ints for safe averaging."""
    if isinstance(value, bool):
        return int(value)
    return value


def _is_circuit_breaker_metric(metric: Dict[str, Any]) -> bool:
    """
    Heuristic circuit-breaker detection for per-spec metrics.

    Supports canonical field names and fallback text matching.
    """
    # Explicit booleans if producers add them.
    for path in (
        ("failure", "circuit_breaker_fired"),
        ("circuit_breaker", "fired"),
        ("research", "circuit_breaker_fired"),
    ):
        container = metric.get(path[0], {})
        if isinstance(container, dict) and container.get(path[1]) is True:
            return True

    failure = metric.get("failure", {})
    if isinstance(failure, dict):
        text = " ".join(
            str(failure.get(k, "")).lower()
            for k in ("error_type", "phase", "description", "root_cause", "suggestion")
        )
        if "circuit_breaker" in text or "circuit breaker" in text:
            return True

    return False


def _make_alert(
    metric: str,
    current: float,
    baseline_average: Optional[float],
    threshold: Any,
    severity: str,
    lookback_used: int,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a normalized regression alert record."""
    alert = {
        "metric": metric,
        "current": current,
        "baseline_average": baseline_average,
        "threshold": threshold,
        "severity": severity,
        "lookback": lookback_used,
    }
    if context:
        alert.update(context)
    return alert


def detect_regressions(metrics, coordinator_metrics=None, lookback=DEFAULT_REGRESSION_LOOKBACK):
    """
    Detect regression alerts based on thresholds.

    Checks:
    - Test pass rate drops >10% vs 5-run average
    - Review cycles increase >50% vs 5-run average
    - Any phase duration >2x its 5-run average
    - Any post-merge failures in latest coordinator run
    - Gap report frequency >30% of specs in latest coordinator run
    - Circuit breaker fires >20% of recent specs
    - Pattern citation rate drops >30% vs 5-run average

    Args:
        metrics (list[dict]): Metrics to analyze
        coordinator_metrics (list[dict] | None): Coordinator run metrics
        lookback (int): Number of runs to use for baseline average

    Returns:
        list[dict]: Regression alerts with current value, baseline average, threshold and severity.
    """
    if len(metrics) < 2:
        # still allow coordinator-only signals
        metrics = metrics or []

    alerts = []

    # Get baseline (last N-1 runs, excluding the current one)
    baseline = metrics[-(lookback + 1):-1] if len(metrics) > lookback else metrics[:-1]
    current = metrics[-1] if metrics else {}

    if current and baseline:
        # Test pass rate regression
        current_pass_rate = current.get("phases", {}).get("validation", {}).get("test_pass_rate")
        baseline_pass_rates = [
            m.get("phases", {}).get("validation", {}).get("test_pass_rate")
            for m in baseline
            if m.get("phases", {}).get("validation", {}).get("test_pass_rate") is not None
        ]
        baseline_avg = _safe_avg([_normalize_metric_value(v) for v in baseline_pass_rates])
        if current_pass_rate is not None and baseline_avg and baseline_avg > 0:
            drop_pct = (baseline_avg - current_pass_rate) / baseline_avg * 100
            if drop_pct > THRESHOLDS["test_pass_rate_drop_pct"]:
                ratio = drop_pct / THRESHOLDS["test_pass_rate_drop_pct"]
                alerts.append(
                    _make_alert(
                        metric="test_pass_rate",
                        current=current_pass_rate,
                        baseline_average=baseline_avg,
                        threshold=f">{THRESHOLDS['test_pass_rate_drop_pct']}%",
                        severity=_severity_from_breach_ratio(ratio),
                        lookback_used=len(baseline_pass_rates),
                        context={"drop_pct": drop_pct},
                    )
                )

        # Review cycles regression
        current_cycles = current.get("phases", {}).get("review", {}).get("cycles")
        baseline_cycles = [
            m.get("phases", {}).get("review", {}).get("cycles")
            for m in baseline
            if m.get("phases", {}).get("review", {}).get("cycles") is not None
        ]
        baseline_avg = _safe_avg([_normalize_metric_value(v) for v in baseline_cycles])
        if current_cycles is not None and baseline_avg and baseline_avg > 0:
            increase_pct = (current_cycles - baseline_avg) / baseline_avg * 100
            if increase_pct > THRESHOLDS["review_cycles_increase_pct"]:
                ratio = increase_pct / THRESHOLDS["review_cycles_increase_pct"]
                alerts.append(
                    _make_alert(
                        metric="review_cycles",
                        current=current_cycles,
                        baseline_average=baseline_avg,
                        threshold=f">{THRESHOLDS['review_cycles_increase_pct']}%",
                        severity=_severity_from_breach_ratio(ratio),
                        lookback_used=len(baseline_cycles),
                        context={"increase_pct": increase_pct},
                    )
                )

    # Phase duration regression
    if current and baseline:
        current_phases = current.get("phases", {})
        for phase_name, phase_data in current_phases.items():
            if phase_name == "execution_mode" or not isinstance(phase_data, dict):
                continue

            current_duration = phase_data.get("duration_s")
            if current_duration is None:
                continue

            baseline_durations = [
                m.get("phases", {}).get(phase_name, {}).get("duration_s")
                for m in baseline
                if isinstance(m.get("phases", {}).get(phase_name, {}), dict)
            ]
            baseline_durations = [d for d in baseline_durations if d is not None]

            baseline_avg = _safe_avg([_normalize_metric_value(v) for v in baseline_durations])
            if baseline_avg and baseline_avg > 0:
                multiplier = current_duration / baseline_avg
                if multiplier > THRESHOLDS["phase_duration_multiplier"]:
                    ratio = multiplier / THRESHOLDS["phase_duration_multiplier"]
                    alerts.append(
                        _make_alert(
                            metric=f"phase_duration_{phase_name}",
                            current=current_duration,
                            baseline_average=baseline_avg,
                            threshold=f">{THRESHOLDS['phase_duration_multiplier']}x",
                            severity=_severity_from_breach_ratio(ratio),
                            lookback_used=len(baseline_durations),
                            context={"multiplier": multiplier},
                        )
                    )

        # Pattern citation rate regression
        current_citation_rate = current.get("knowledge", {}).get("citation_rate")
        baseline_citation_rates = [
            m.get("knowledge", {}).get("citation_rate")
            for m in baseline
            if isinstance(m.get("knowledge"), dict) and m.get("knowledge", {}).get("citation_rate") is not None
        ]
        baseline_avg = _safe_avg([_normalize_metric_value(v) for v in baseline_citation_rates])
        if current_citation_rate is not None and baseline_avg and baseline_avg > 0:
            drop_pct = (baseline_avg - current_citation_rate) / baseline_avg * 100
            if drop_pct > THRESHOLDS["pattern_citation_rate_drop_pct"]:
                ratio = drop_pct / THRESHOLDS["pattern_citation_rate_drop_pct"]
                alerts.append(
                    _make_alert(
                        metric="pattern_citation_rate",
                        current=current_citation_rate,
                        baseline_average=baseline_avg,
                        threshold=f">{THRESHOLDS['pattern_citation_rate_drop_pct']}%",
                        severity=_severity_from_breach_ratio(ratio),
                        lookback_used=len(baseline_citation_rates),
                        context={"drop_pct": drop_pct},
                    )
                )

        # Circuit breaker frequency (last lookback specs)
        window = metrics[-lookback:] if len(metrics) >= lookback else metrics
        if window:
            fired_count = sum(1 for m in window if _is_circuit_breaker_metric(m))
            frequency = fired_count / len(window)
            threshold = THRESHOLDS["circuit_breaker_frequency_pct"] / 100
            if frequency > threshold:
                previous_window = metrics[-(2 * lookback):-lookback] if len(metrics) > lookback else []
                previous_frequency = None
                if previous_window:
                    previous_fired = sum(1 for m in previous_window if _is_circuit_breaker_metric(m))
                    previous_frequency = previous_fired / len(previous_window)
                ratio = frequency / threshold if threshold > 0 else 1
                alerts.append(
                    _make_alert(
                        metric="circuit_breaker_frequency",
                        current=frequency,
                        baseline_average=previous_frequency,
                        threshold=f">{THRESHOLDS['circuit_breaker_frequency_pct']}%",
                        severity=_severity_from_breach_ratio(ratio),
                        lookback_used=len(window),
                        context={"fired_specs": fired_count, "window_specs": len(window)},
                    )
                )

    # Coordinator-derived regressions.
    coordinator_metrics = coordinator_metrics or []
    if coordinator_metrics:
        coordinator_metrics = sorted(
            coordinator_metrics,
            key=lambda m: _parse_iso8601(m.get("started_at")),
        )
        current_coord = coordinator_metrics[-1]
        baseline_coord = (
            coordinator_metrics[-(lookback + 1):-1]
            if len(coordinator_metrics) > lookback
            else coordinator_metrics[:-1]
        )

        # Post-merge failures: any non-green validation in latest run.
        post_merge = current_coord.get("post_merge_validations", [])
        post_merge_failures = sum(
            1
            for v in post_merge
            if isinstance(v, dict) and v.get("main_green_after_merge") is False
        )
        baseline_post_merge = [
            sum(
                1
                for v in m.get("post_merge_validations", [])
                if isinstance(v, dict) and v.get("main_green_after_merge") is False
            )
            for m in baseline_coord
        ]
        baseline_avg = _safe_avg([_normalize_metric_value(v) for v in baseline_post_merge])
        if post_merge_failures > 0:
            alerts.append(
                _make_alert(
                    metric="post_merge_failures",
                    current=post_merge_failures,
                    baseline_average=baseline_avg,
                    threshold="0 occurrences",
                    severity="critical",
                    lookback_used=len(baseline_post_merge),
                )
            )

        # Gap report frequency in latest coordinator run.
        queued = current_coord.get("specs_queued", 0) or 0
        gapped = current_coord.get("specs_gapped", 0) or 0
        gap_frequency = (gapped / queued) if queued > 0 else 0
        threshold = THRESHOLDS["gap_report_frequency_pct"] / 100
        baseline_gap_rates = []
        for m in baseline_coord:
            bq = m.get("specs_queued", 0) or 0
            bg = m.get("specs_gapped", 0) or 0
            if bq > 0:
                baseline_gap_rates.append(bg / bq)
        baseline_avg = _safe_avg([_normalize_metric_value(v) for v in baseline_gap_rates])
        if gap_frequency > threshold:
            ratio = gap_frequency / threshold if threshold > 0 else 1
            alerts.append(
                _make_alert(
                    metric="gap_report_frequency",
                    current=gap_frequency,
                    baseline_average=baseline_avg,
                    threshold=f">{THRESHOLDS['gap_report_frequency_pct']}%",
                    severity=_severity_from_breach_ratio(ratio),
                    lookback_used=len(baseline_gap_rates),
                    context={"gapped_specs": gapped, "queued_specs": queued},
                )
            )

    return alerts


def generate_markdown_report(trends, breakdown, model_comparison=None, alerts=None):
    """
    Generate human-readable Markdown trend report.

    Args:
        trends (dict): Output from compute_trends()
        breakdown (dict): Output from compute_phase_breakdown()
        model_comparison (dict, optional): Output from compute_model_comparison()
        alerts (list, optional): Regression alerts

    Returns:
        str: Markdown formatted report
    """
    lines = [
        "# Metrics Trend Report",
        "",
        "## Summary",
        "",
    ]

    # Completion rate
    if "completion_rate" in trends:
        cr = trends["completion_rate"]
        lines.append(f"- **Completion Rate:** {cr['completed']}/{cr['total']} ({cr['value']*100:.1f}%)")

    lines.append("")

    # Trends section
    lines.append("## Trends (Last 10 Runs)")
    lines.append("")

    if "test_pass_rate" in trends:
        tr = trends["test_pass_rate"]
        direction = tr["direction"]
        avg = tr["average"]
        lines.append(f"- **Test Pass Rate:** {avg:.2%} {direction}")

    if "overall_satisfaction" in trends:
        os = trends["overall_satisfaction"]
        direction = os["direction"]
        avg = os["average"]
        lines.append(f"- **Overall Satisfaction:** {avg:.2f}/1.0 {direction}")

    if "review_cycles" in trends:
        rc = trends["review_cycles"]
        direction = rc["direction"]
        avg = rc["average"]
        lines.append(f"- **Avg Review Cycles:** {avg:.1f} {direction}")

    if "average_spec_duration_s" in trends:
        asd = trends["average_spec_duration_s"]
        direction = asd["direction"]
        avg = asd["average"]
        lines.append(f"- **Avg Spec Duration:** {avg:.0f}s {direction}")

    lines.append("")

    # Phase breakdown
    lines.append("## Phase Breakdown (by Duration)")
    lines.append("")
    for phase in breakdown["phases"]:
        lines.append(f"- **{phase['name']}:** {phase['average_duration_s']:.0f}s avg ({phase['runs']} runs)")

    lines.append("")
    lines.append(f"**Total Avg Duration:** {breakdown['total_average_s']:.0f}s")
    lines.append("")

    # Model comparison
    if model_comparison:
        lines.append("## Model Comparison")
        lines.append("")
        for model, stats in sorted(model_comparison.items()):
            lines.append(f"### {model}")
            lines.append(f"- Runs: {stats['runs']}")
            lines.append(f"- Avg Satisfaction: {stats['avg_satisfaction']:.2f}/1.0")
            lines.append(f"- Avg Duration: {stats['avg_duration_s']:.0f}s")
            lines.append(f"- Completion Rate: {stats['completion_rate']*100:.1f}%")
            lines.append("")

    # Alerts
    if alerts:
        lines.append("## Regression Alerts")
        lines.append("")
        for alert in alerts:
            metric = alert["metric"]
            prev = alert.get("baseline_average")
            curr = alert.get("current")
            severity = alert.get("severity", "medium")
            lines.append(f"⚠️ **{metric}** regressed")
            lines.append(f"   - Severity: {severity.upper()}")
            lines.append(f"   - Baseline (avg): {prev if prev is not None else 'N/A'}")
            lines.append(f"   - Current: {curr if curr is not None else 'N/A'}")
            lines.append("")

    return "\n".join(lines)


def generate_json_output(trends, breakdown, model_comparison=None, alerts=None, files_analyzed=0, gap_analytics=None):
    """
    Generate machine-readable JSON output.

    Args:
        trends (dict): Output from compute_trends()
        breakdown (dict): Output from compute_phase_breakdown()
        model_comparison (dict, optional): Output from compute_model_comparison()
        alerts (list, optional): Regression alerts
        files_analyzed (int): Number of metrics files analyzed

    Returns:
        str: JSON formatted output
    """
    output = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "files_analyzed": files_analyzed,
        "trends": trends,
        "phase_breakdown": breakdown,
        "model_comparison": model_comparison or {},
        "regression_alerts": alerts or [],
        "gap_analytics": gap_analytics or {},
    }

    return json.dumps(output, indent=2, default=str)


def write_regression_alert(alerts, reports_dir_path):
    """
    Write regression alerts to .nightshift/reports/REGRESSION-ALERT.md.

    Args:
        alerts (list[dict]): Regression alerts from detect_regressions()
        reports_dir_path (str): Path to reports directory

    Returns:
        Path: Path to written alert file
    """
    reports_dir = Path(reports_dir_path)
    reports_dir.mkdir(parents=True, exist_ok=True)

    alert_file = reports_dir / "REGRESSION-ALERT.md"

    lines = [
        "# REGRESSION ALERT",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "The following metrics have degraded beyond acceptable thresholds:",
        "",
    ]

    for alert in alerts:
        metric = alert["metric"]
        prev = alert.get("baseline_average", "N/A")
        curr = alert.get("current", "N/A")
        lookback = alert.get("lookback", "N/A")
        severity = alert.get("severity", "medium")

        lines.append(f"## {metric}")
        lines.append(f"- **Severity:** {severity.upper()}")
        lines.append(f"- **Baseline average ({lookback} runs):** {prev}")
        lines.append(f"- **Current:** {curr}")
        lines.append(f"- **Threshold:** {alert.get('threshold', 'N/A')}")

        if "drop_pct" in alert:
            lines.append(f"- **Drop:** {alert['drop_pct']:.1f}%")
        elif "increase_pct" in alert:
            lines.append(f"- **Increase:** {alert['increase_pct']:.1f}%")
        elif "multiplier" in alert:
            lines.append(f"- **Multiplier:** {alert['multiplier']:.2f}x")
        elif metric in {"gap_report_frequency", "circuit_breaker_frequency"}:
            lines.append(f"- **Rate:** {curr * 100:.1f}%")

        lines.append("")

    alert_file.write_text("\n".join(lines))
    return alert_file


def write_regression_status_snapshot(alerts, reports_dir_path):
    """
    Write a status snapshot used by /nightshift status to surface latest alerts.

    Returns:
        Path: Path to the written JSON status snapshot.
    """
    reports_dir = Path(reports_dir_path)
    reports_dir.mkdir(parents=True, exist_ok=True)
    status_file = reports_dir / "REGRESSION-STATUS.json"

    severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    highest = "low"
    for alert in alerts:
        sev = str(alert.get("severity", "medium")).lower()
        if severity_rank.get(sev, 0) > severity_rank.get(highest, 0):
            highest = sev

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "has_alerts": bool(alerts),
        "alert_count": len(alerts),
        "highest_severity": highest if alerts else "none",
        "alerts": [
            {
                "metric": a.get("metric"),
                "severity": a.get("severity", "medium"),
                "current": a.get("current"),
                "baseline_average": a.get("baseline_average"),
                "threshold": a.get("threshold"),
            }
            for a in alerts
        ],
    }
    status_file.write_text(json.dumps(payload, indent=2, default=str))
    return status_file


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Cross-run metrics analyzer for Nightshift"
    )
    parser.add_argument(
        "metrics_dir",
        help="Path to metrics directory (containing .yaml files)",
    )
    parser.add_argument(
        "--since",
        help="Only analyze runs after this date (YYYY-MM-DD)",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--compare-models",
        action="store_true",
        help="Generate model comparison report",
    )

    args = parser.parse_args()

    # Load metrics
    metrics = load_metrics_files(args.metrics_dir)

    if not metrics:
        print("No valid metrics files found.", file=sys.stderr)
        sys.exit(EXIT_SUCCESS)

    # Apply date filter
    if args.since:
        try:
            since_date = datetime.strptime(args.since, "%Y-%m-%d")
            metrics = filter_by_date(metrics, since_date)
        except ValueError:
            print(f"Error: Invalid date format '{args.since}'. Use YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)

    if not metrics:
        print("No metrics after the specified date.", file=sys.stderr)
        sys.exit(EXIT_SUCCESS)

    # Compute analysis
    trends = compute_trends(metrics)
    breakdown = compute_phase_breakdown(metrics)
    model_comparison = compute_model_comparison(metrics) if args.compare_models else None

    # Detect regressions
    coordinator_metrics = load_coordinator_metrics(args.metrics_dir)
    alerts = detect_regressions(metrics, coordinator_metrics=coordinator_metrics)
    gap_reports = load_gap_reports(args.metrics_dir)
    gap_analytics = compute_gap_analytics(gap_reports)

    # Ensure output directories exist
    project_root = Path(args.metrics_dir).parent
    reports_dir = project_root / "reports"
    metrics_dir = project_root / "metrics"

    reports_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    # Write reports
    markdown = generate_markdown_report(trends, breakdown, model_comparison, alerts)
    (reports_dir / "metrics-trend.md").write_text(markdown)

    json_output = generate_json_output(
        trends, breakdown, model_comparison, alerts, len(metrics), gap_analytics=gap_analytics
    )
    (metrics_dir / "analysis.json").write_text(json_output)
    status_snapshot = write_regression_status_snapshot(alerts, str(reports_dir))
    gap_report_file = write_gap_analytics_report(gap_analytics, str(reports_dir))
    gap_status_snapshot = write_gap_analytics_status_snapshot(gap_analytics, str(reports_dir))

    # Write regression alerts if any
    if alerts:
        write_regression_alert(alerts, str(reports_dir))

    # Print summary
    print(f"Analyzed {len(metrics)} metrics files")
    print(f"Trend report: {reports_dir / 'metrics-trend.md'}")
    print(f"Gap analytics report: {gap_report_file}")
    print(f"Analysis JSON: {metrics_dir / 'analysis.json'}")
    print(f"Regression status snapshot: {status_snapshot}")
    print(f"Gap analytics status snapshot: {gap_status_snapshot}")

    if alerts:
        print(f"Regression alerts: {reports_dir / 'REGRESSION-ALERT.md'}")
        sys.exit(EXIT_REGRESSION_DETECTED)
    else:
        sys.exit(EXIT_SUCCESS)


if __name__ == "__main__":
    main()
