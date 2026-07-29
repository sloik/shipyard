#!/usr/bin/env python3
"""
Metrics Fidelity Checks (SPEC-047)
==================================

Plausibility warnings for per-spec Nightshift metrics YAML files. These are
*warnings*, not schema errors — they catch patterns characteristic of
fabricated (as opposed to shell-captured) timestamps and durations, without
blocking runs that happen to produce round numbers legitimately.

Warning codes emitted:
  - ``timestamp_round_minute``           — ≥2 timestamps in a single file land on 5-minute boundaries
  - ``duration_zero``                    — a phase reports ``duration_s == 0``
  - ``duration_round``                   — a sub-5-minute phase reports a non-zero multiple of 300s
  - ``timestamp_duplicate_across_specs`` — two different specs in the same run share a second-precision start timestamp
  - ``duration_impossibly_fast``         — a phase finished faster than the domain/phase minimum in metric-ranges.yaml
  - ``timestamp_drift_vs_shell``         — metrics YAML ``started_at``/``completed_at`` differs from shell-captured value in events.jsonl by more than the allowed delta

Escalation:
  - ``metrics_fidelity_low`` event at severity ``high`` emitted to events.jsonl
    when a single run accumulates ≥3 warnings (across files). The run still
    completes — this is observational, not a gate.

This module is intentionally independent of ``validate_metrics.py`` so the
existing schema validator's behaviour (and its test suite) is untouched.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover — import guard
    print(
        "Error: PyYAML is required for metrics_fidelity. "
        "Install with: pip install pyyaml",
        file=sys.stderr,
    )
    raise


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

DEFAULT_ROUND_MINUTE_BOUNDARY = 300            # seconds — 5-minute ladder
DEFAULT_ROUND_MINUTE_MIN_HITS = 2              # ≥2 round-minute timestamps per file → warn
DEFAULT_DURATION_ROUND_BOUNDARY = 300          # seconds
DEFAULT_DURATION_ROUND_TYPICAL_THRESHOLD = 300 # only flag round durations when typical_s < this
DEFAULT_TIMESTAMP_DRIFT_S = 1.0                # AC7 — YAML vs shell tolerance
DEFAULT_FIDELITY_EVENT_THRESHOLD = 3           # R5 — ≥N warnings → metrics_fidelity_low


# --------------------------------------------------------------------------- #
# Data classes                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class FidelityWarning:
    """One plausibility warning. Stable schema for JSON/markdown rendering."""

    code: str
    message: str
    spec_id: Optional[str] = None
    file: Optional[str] = None
    phase: Optional[str] = None
    field: Optional[str] = None
    expected: Optional[Any] = None
    actual: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# --------------------------------------------------------------------------- #
# metric-ranges.yaml loading                                                  #
# --------------------------------------------------------------------------- #


def default_metric_ranges_path() -> Path:
    """Canonical metric-ranges.yaml bundled with the kit."""
    return Path(__file__).resolve().parent / "metric-ranges.yaml"


def load_metric_ranges(path: Optional[Path] = None) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    Load metric-ranges.yaml.

    Returns a mapping ``{domain: {phase: {min_s, max_s, typical_s}}}``.
    If ``path`` is None the kit's canonical file is used. Missing file or
    parse failure → empty dict (checks degrade to skip, never crash).
    """
    target = Path(path) if path is not None else default_metric_ranges_path()
    if not target.exists():
        return {}
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Normalise: every phase dict must be a dict.
    cleaned: Dict[str, Dict[str, Dict[str, float]]] = {}
    for domain, phases in data.items():
        if not isinstance(phases, dict):
            continue
        cleaned[domain] = {}
        for phase, cfg in phases.items():
            if isinstance(cfg, dict):
                cleaned[domain][phase] = cfg
    return cleaned


def resolve_phase_range(
    ranges: Dict[str, Dict[str, Dict[str, float]]],
    domain: Optional[str],
    phase: str,
) -> Dict[str, float]:
    """Look up a phase's range with fallback to ``code`` then empty dict."""
    for key in filter(None, [domain, "code"]):
        per_domain = ranges.get(key) or {}
        if phase in per_domain:
            return per_domain[phase]
    return {}


# --------------------------------------------------------------------------- #
# Timestamp helpers                                                           #
# --------------------------------------------------------------------------- #


ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
)


def parse_iso8601(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    normalised = value.replace("+00:00", "Z")
    for fmt in ISO_FORMATS:
        try:
            dt = datetime.strptime(normalised, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _epoch_seconds(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _is_round_minute(dt: datetime, boundary: int = DEFAULT_ROUND_MINUTE_BOUNDARY) -> bool:
    """True when ``dt`` lands exactly on a ``boundary``-second grid (and :00 seconds)."""
    return int(_epoch_seconds(dt)) % boundary == 0


# --------------------------------------------------------------------------- #
# Per-file checks                                                             #
# --------------------------------------------------------------------------- #


PHASE_FIELDS = (
    "preflight",
    "context_load",
    "test_planning",
    "test_writing",
    "implementation",
    "review",
    "validation",
    "completion_verification",
    "synthesis_gate",
)


def _file_label(data: Dict[str, Any], path: Optional[Path]) -> Tuple[Optional[str], Optional[str]]:
    spec_id = data.get("task_id") if isinstance(data, dict) else None
    filename = path.name if path is not None else None
    return spec_id, filename


def _check_round_minute(
    data: Dict[str, Any],
    spec_id: Optional[str],
    filename: Optional[str],
    min_hits: int = DEFAULT_ROUND_MINUTE_MIN_HITS,
) -> List[FidelityWarning]:
    candidates: List[Tuple[str, str, datetime]] = []
    for field_name in ("started_at", "completed_at"):
        dt = parse_iso8601(data.get(field_name))
        if dt is not None:
            candidates.append((field_name, str(data.get(field_name)), dt))

    phases = data.get("phases") if isinstance(data.get("phases"), dict) else {}
    for phase_name, phase_data in phases.items():
        if not isinstance(phase_data, dict):
            continue
        for sub in ("started_at", "completed_at", "start", "end"):
            dt = parse_iso8601(phase_data.get(sub))
            if dt is not None:
                candidates.append((f"phases.{phase_name}.{sub}", str(phase_data.get(sub)), dt))

    round_hits = [(f, raw) for (f, raw, dt) in candidates if _is_round_minute(dt)]
    if len(round_hits) >= min_hits:
        fields = ", ".join(f for f, _ in round_hits)
        raw_values = ", ".join(raw for _, raw in round_hits)
        return [
            FidelityWarning(
                code="timestamp_round_minute",
                message=(
                    f"{len(round_hits)} timestamps fall on 5-minute boundaries "
                    f"({fields}); characteristic of fabricated values "
                    f"(observed: {raw_values})."
                ),
                spec_id=spec_id,
                file=filename,
                actual=[raw for _, raw in round_hits],
            )
        ]
    return []


def _check_durations(
    data: Dict[str, Any],
    ranges: Dict[str, Dict[str, Dict[str, float]]],
    spec_id: Optional[str],
    filename: Optional[str],
) -> List[FidelityWarning]:
    warnings: List[FidelityWarning] = []
    domain = data.get("domain") if isinstance(data.get("domain"), str) else None
    phases = data.get("phases") if isinstance(data.get("phases"), dict) else {}
    for phase_name in PHASE_FIELDS:
        phase_data = phases.get(phase_name)
        if not isinstance(phase_data, dict):
            continue
        duration = phase_data.get("duration_s")
        if duration is None:
            continue
        if not isinstance(duration, (int, float)):
            # Schema validator owns type errors — not our concern.
            continue

        # duration_zero — R1
        if duration == 0:
            warnings.append(
                FidelityWarning(
                    code="duration_zero",
                    message=(
                        f"phases.{phase_name}.duration_s is 0 — phase boundary "
                        f"was not shell-captured."
                    ),
                    spec_id=spec_id,
                    file=filename,
                    phase=phase_name,
                    field="duration_s",
                    actual=duration,
                )
            )
            # Skip the round/fast checks for zero duration — already flagged.
            continue

        phase_range = resolve_phase_range(ranges, domain, phase_name)

        # duration_impossibly_fast — R1
        min_s = phase_range.get("min_s")
        if isinstance(min_s, (int, float)) and duration < min_s:
            warnings.append(
                FidelityWarning(
                    code="duration_impossibly_fast",
                    message=(
                        f"phases.{phase_name}.duration_s={duration}s is below "
                        f"the domain minimum ({min_s}s for domain "
                        f"{domain or 'code'})."
                    ),
                    spec_id=spec_id,
                    file=filename,
                    phase=phase_name,
                    field="duration_s",
                    expected={"min_s": min_s, "domain": domain or "code"},
                    actual=duration,
                )
            )
            continue

        # duration_round — R1. Only suspicious for phases that typically
        # finish in under 5 minutes; a 300s implementation (typical 120s) is
        # suspicious, but a 900s validation for a slow test-suite isn't.
        typical_s = phase_range.get("typical_s")
        is_multiple_of_boundary = (
            duration > 0
            and duration % DEFAULT_DURATION_ROUND_BOUNDARY == 0
        )
        if is_multiple_of_boundary and (
            typical_s is None
            or (
                isinstance(typical_s, (int, float))
                and typical_s < DEFAULT_DURATION_ROUND_TYPICAL_THRESHOLD
            )
        ):
            warnings.append(
                FidelityWarning(
                    code="duration_round",
                    message=(
                        f"phases.{phase_name}.duration_s={duration}s is an "
                        f"exact multiple of 5 minutes for a sub-5-minute "
                        f"phase — characteristic of estimated durations."
                    ),
                    spec_id=spec_id,
                    file=filename,
                    phase=phase_name,
                    field="duration_s",
                    actual=duration,
                )
            )

    return warnings


def check_file_fidelity(
    path: Path,
    ranges: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None,
) -> List[FidelityWarning]:
    """Run per-file fidelity checks on one metrics YAML."""
    path = Path(path)
    if ranges is None:
        ranges = load_metric_ranges()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []

    spec_id, filename = _file_label(data, path)
    warnings: List[FidelityWarning] = []
    warnings.extend(_check_round_minute(data, spec_id, filename))
    warnings.extend(_check_durations(data, ranges, spec_id, filename))
    return warnings


# --------------------------------------------------------------------------- #
# Cross-file checks                                                           #
# --------------------------------------------------------------------------- #


def _check_duplicate_start_times(files: List[Tuple[Path, Dict[str, Any]]]) -> List[FidelityWarning]:
    """Two different specs in a run must not share a second-precision start."""
    by_timestamp: Dict[str, List[Tuple[str, str]]] = {}
    for path, data in files:
        started = data.get("started_at")
        spec_id = data.get("task_id") or path.stem
        if not isinstance(started, str) or not parse_iso8601(started):
            continue
        by_timestamp.setdefault(started, []).append((str(spec_id), path.name))

    warnings: List[FidelityWarning] = []
    for started, entries in by_timestamp.items():
        if len(entries) < 2:
            continue
        # Only flag when two *different* spec IDs share the timestamp.
        unique_specs = {spec for spec, _ in entries}
        if len(unique_specs) < 2:
            continue
        warnings.append(
            FidelityWarning(
                code="timestamp_duplicate_across_specs",
                message=(
                    f"{len(entries)} specs share started_at={started!r}: "
                    f"{', '.join(sorted(unique_specs))} — sequential loops "
                    f"cannot produce identical second-precision starts."
                ),
                spec_id=None,
                file=None,
                actual={"started_at": started, "specs": sorted(unique_specs)},
            )
        )
    return warnings


# --------------------------------------------------------------------------- #
# Shell-captured timestamp cross-check (R2)                                   #
# --------------------------------------------------------------------------- #


STEP_TIMESTAMP_EVENT = "step_timestamp"


def load_step_timestamps(events_file: Optional[Path]) -> Dict[int, List[Dict[str, Any]]]:
    """
    Parse events.jsonl and return shell-captured step_timestamp events keyed by step number.
    Missing file → empty dict. Malformed lines are skipped silently.
    """
    if events_file is None:
        return {}
    path = Path(events_file)
    if not path.exists():
        return {}
    by_step: Dict[int, List[Dict[str, Any]]] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("event") != STEP_TIMESTAMP_EVENT:
                    continue
                step = event.get("step")
                if isinstance(step, int):
                    by_step.setdefault(step, []).append(event)
    except OSError:
        return {}
    return by_step


def _nearest_shell_epoch(events: List[Dict[str, Any]], spec_id: Optional[str]) -> Optional[float]:
    """Pick the step_timestamp event most likely to match this spec."""
    if not events:
        return None
    if spec_id:
        for event in events:
            if event.get("spec_id") == spec_id and isinstance(event.get("epoch"), (int, float)):
                return float(event["epoch"])
    # Fallback — first event with an epoch.
    for event in events:
        if isinstance(event.get("epoch"), (int, float)):
            return float(event["epoch"])
    return None


def _check_timestamp_drift(
    data: Dict[str, Any],
    path: Path,
    shell_by_step: Dict[int, List[Dict[str, Any]]],
    tolerance_s: float = DEFAULT_TIMESTAMP_DRIFT_S,
) -> List[FidelityWarning]:
    warnings: List[FidelityWarning] = []
    spec_id = data.get("task_id") if isinstance(data.get("task_id"), str) else None

    pairs = (
        ("started_at", 1),   # Step 1 captured LOOP_START
        ("completed_at", 13) # Step 13 captured LOOP_END
    )
    for yaml_field, step_number in pairs:
        yaml_dt = parse_iso8601(data.get(yaml_field))
        if yaml_dt is None:
            continue
        shell_epoch = _nearest_shell_epoch(shell_by_step.get(step_number, []), spec_id)
        if shell_epoch is None:
            continue
        drift = abs(_epoch_seconds(yaml_dt) - shell_epoch)
        if drift > tolerance_s:
            warnings.append(
                FidelityWarning(
                    code="timestamp_drift_vs_shell",
                    message=(
                        f"{yaml_field} drifts {drift:.1f}s from shell-captured "
                        f"step_timestamp (step {step_number}); tolerance "
                        f"{tolerance_s}s."
                    ),
                    spec_id=spec_id,
                    file=path.name,
                    field=yaml_field,
                    expected={"shell_epoch": shell_epoch, "tolerance_s": tolerance_s},
                    actual={"yaml_epoch": _epoch_seconds(yaml_dt), "drift_s": drift},
                )
            )
    return warnings


# --------------------------------------------------------------------------- #
# Top-level run check                                                         #
# --------------------------------------------------------------------------- #


@dataclass
class RunFidelityResult:
    warnings: List[FidelityWarning] = field(default_factory=list)
    files_checked: int = 0
    escalated: bool = False  # metrics_fidelity_low emitted?

    @property
    def count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "warnings": [w.to_dict() for w in self.warnings],
            "files_checked": self.files_checked,
            "count": self.count,
            "escalated": self.escalated,
        }


def _iter_metric_files(directory: Path) -> List[Path]:
    files = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
    # Skip the schema doc if someone dropped it alongside real files.
    return sorted(f for f in files if f.is_file() and not f.name.startswith("_"))


def check_run_fidelity(
    metrics_dir: Path,
    events_file: Optional[Path] = None,
    ranges_path: Optional[Path] = None,
    escalation_threshold: int = DEFAULT_FIDELITY_EVENT_THRESHOLD,
    emit_escalation: bool = True,
) -> RunFidelityResult:
    """
    Run the full fidelity suite over every metrics YAML in ``metrics_dir``.

    If ``events_file`` is provided, the shell-timestamp cross-check runs and
    — when warnings ≥ ``escalation_threshold`` — a ``metrics_fidelity_low``
    event at severity ``high`` is appended to that same file (controlled by
    ``emit_escalation`` so tests can observe the result without duplicating
    the append side-effect).
    """
    metrics_dir = Path(metrics_dir)
    ranges = load_metric_ranges(ranges_path)
    shell_by_step = load_step_timestamps(events_file)

    result = RunFidelityResult()
    if not metrics_dir.is_dir():
        return result

    loaded: List[Tuple[Path, Dict[str, Any]]] = []
    for path in _iter_metric_files(metrics_dir):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        loaded.append((path, data))

    result.files_checked = len(loaded)
    for path, data in loaded:
        result.warnings.extend(check_file_fidelity(path, ranges=ranges))
        if shell_by_step:
            result.warnings.extend(_check_timestamp_drift(data, path, shell_by_step))
    result.warnings.extend(_check_duplicate_start_times(loaded))

    if result.count >= escalation_threshold:
        result.escalated = True
        if emit_escalation and events_file is not None:
            _emit_fidelity_event(events_file, result)

    return result


# --------------------------------------------------------------------------- #
# Event emission                                                              #
# --------------------------------------------------------------------------- #


def _emit_fidelity_event(events_file: Path, result: RunFidelityResult) -> None:
    """Append a metrics_fidelity_low event (severity high) to events.jsonl.

    Idempotent: if an identical escalation (same warning_count and same sorted
    warning_codes) is already present, no new line is appended. This matters
    because Step 14 runs per-spec — in a 10-spec run with fabricated
    timestamps the validator would otherwise emit 10 duplicate escalations.
    """
    events_file = Path(events_file)
    try:
        events_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    # Derive run_id from the path when the event log layout is known:
    # .../.nightshift/runs/<run_id>/events.jsonl
    run_id = None
    parts = events_file.parts
    if "runs" in parts:
        try:
            idx = parts.index("runs")
            run_id = parts[idx + 1]
        except (IndexError, ValueError):
            run_id = None

    warning_codes = sorted({w.code for w in result.warnings})
    warning_count = result.count

    # Idempotency guard — skip emission if an identical escalation is
    # already on disk for this run.
    if events_file.exists():
        try:
            with open(events_file, "r", encoding="utf-8") as handle:
                for raw in handle:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        existing = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(existing, dict):
                        continue
                    if existing.get("event") != "metrics_fidelity_low":
                        continue
                    if (
                        existing.get("warning_count") == warning_count
                        and existing.get("warning_codes") == warning_codes
                    ):
                        return
        except OSError:
            pass

    payload = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": "metrics_fidelity_low",
        "severity": "high",
        "run_id": run_id,
        "spec_id": None,
        "warning_count": warning_count,
        "warning_codes": warning_codes,
        "source": "metrics_fidelity.check_run_fidelity",
    }
    try:
        with open(events_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        return


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #


CLEAN_MESSAGE = "_All metric fidelity checks passed._"


def render_markdown(result: RunFidelityResult) -> str:
    """Render a ``## Metrics Fidelity`` markdown section for Step 14 reports."""
    lines: List[str] = ["## Metrics Fidelity", ""]
    if result.count == 0:
        lines.append(CLEAN_MESSAGE)
        lines.append("")
        return "\n".join(lines)

    lines.append(f"**{result.count} warnings across {result.files_checked} metrics file(s).**")
    lines.append("")
    lines.append("| Code | Spec | File | Phase / Field | Detail |")
    lines.append("|---|---|---|---|---|")
    for w in result.warnings:
        phase_field = "/".join(filter(None, [w.phase, w.field])) or "—"
        detail = w.message.replace("|", "\\|")
        lines.append(
            f"| `{w.code}` | {w.spec_id or '—'} | {w.file or '—'} | "
            f"{phase_field} | {detail} |"
        )
    if result.escalated:
        lines.append("")
        lines.append(
            "> `metrics_fidelity_low` event emitted at severity `high` "
            "(≥3 warnings — see events.jsonl)."
        )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _cli(argv: List[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="metrics_fidelity",
        description="Plausibility checks for Nightshift metrics YAMLs (SPEC-047).",
    )
    parser.add_argument(
        "metrics_dir",
        help="Directory of per-spec metrics YAMLs (e.g. .nightshift/metrics)",
    )
    parser.add_argument(
        "--events-file",
        default=None,
        help=(
            "Path to the run's events.jsonl. When provided, shell-timestamp "
            "cross-checks run and metrics_fidelity_low is appended on ≥3 warnings."
        ),
    )
    parser.add_argument(
        "--ranges",
        default=None,
        help="Path to a custom metric-ranges.yaml (defaults to the kit's copy).",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--no-escalate",
        action="store_true",
        help="Do not append metrics_fidelity_low to events.jsonl even on ≥3 warnings.",
    )
    args = parser.parse_args(argv)

    result = check_run_fidelity(
        Path(args.metrics_dir),
        events_file=Path(args.events_file) if args.events_file else None,
        ranges_path=Path(args.ranges) if args.ranges else None,
        emit_escalation=not args.no_escalate,
    )

    if args.format == "markdown":
        sys.stdout.write(render_markdown(result))
    else:
        json.dump(result.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    # Warnings are informational — exit 0 regardless.
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
