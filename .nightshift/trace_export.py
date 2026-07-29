#!/usr/bin/env python3
"""SPEC-095: Export failed run traces as replayable regression eval cases."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "nightshift.regression_trace.v1"
FAILING_STEPS = frozenset({"retrieval", "processing", "generation"})

# Keep this list as the AIE log-everything contract. The exported case stores
# these names verbatim under ``aie_required_fields`` and requires matching data
# under ``trace``.
AIE_REQUIRED_FIELDS = (
    "model_endpoint",
    "model_name",
    "sampling_params",
    "prompt_template",
    "user_query",
    "final_prompt_sent",
    "output",
    "intermediate_outputs",
    "tool_calls",
    "component_events",
)

SAMPLING_PARAM_FIELDS = ("temperature", "top_p", "top_k", "stop")


class TraceExportError(ValueError):
    """Raised when a failure trace cannot become a replayable eval case."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return slug or "trace"


def default_case_id(*, source_file: str, failing_step: str, timestamp: str | None = None) -> str:
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source = _slug(Path(source_file).stem)
    return f"TRACE-{stamp}-{_slug(failing_step)}-{source}"


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TraceExportError(f"{field} must be a mapping")
    return value


def _require_id_mapping(item: Any, field: str, index: int, *, required: tuple[str, ...] = ()) -> None:
    if not isinstance(item, Mapping):
        raise TraceExportError(f"{field}[{index}] must be a mapping")
    if not item.get("id"):
        raise TraceExportError(f"{field}[{index}] must include an id")
    for key in required:
        if key not in item:
            raise TraceExportError(f"{field}[{index}] must include {key}")


def validate_trace(trace: Mapping[str, Any]) -> None:
    """Validate the AIE replayable field set required by SPEC-095."""
    missing = [field for field in AIE_REQUIRED_FIELDS if field not in trace]
    if missing:
        raise TraceExportError("trace missing AIE fields: " + ", ".join(missing))

    field_ids = _require_mapping(trace.get("field_ids"), "trace.field_ids")
    missing_ids = [field for field in AIE_REQUIRED_FIELDS if not field_ids.get(field)]
    if missing_ids:
        raise TraceExportError("trace.field_ids missing IDs for: " + ", ".join(missing_ids))

    sampling = _require_mapping(trace["sampling_params"], "trace.sampling_params")
    missing_sampling = [field for field in SAMPLING_PARAM_FIELDS if field not in sampling]
    if missing_sampling:
        raise TraceExportError("trace.sampling_params missing: " + ", ".join(missing_sampling))

    if not isinstance(trace["intermediate_outputs"], list):
        raise TraceExportError("trace.intermediate_outputs must be a list")
    for index, item in enumerate(trace["intermediate_outputs"]):
        _require_id_mapping(item, "trace.intermediate_outputs", index, required=("output",))

    if not isinstance(trace["tool_calls"], list):
        raise TraceExportError("trace.tool_calls must be a list")
    for index, item in enumerate(trace["tool_calls"]):
        _require_id_mapping(item, "trace.tool_calls", index, required=("tool_name", "arguments", "output"))

    if not isinstance(trace["component_events"], list):
        raise TraceExportError("trace.component_events must be a list")
    for index, item in enumerate(trace["component_events"]):
        _require_id_mapping(item, "trace.component_events", index, required=("component_id", "event_type"))
        if item.get("event_type") not in {"start", "end", "crash"}:
            raise TraceExportError(
                f"trace.component_events[{index}].event_type must be start, end, or crash"
            )


def build_case(
    *,
    trace: Mapping[str, Any],
    failing_step: str,
    expected_output: Any,
    source_file: str,
    error_type: str,
    description: str,
    status: str = "failed",
    case_id: str | None = None,
    title: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a regression eval case from a failed run trace."""
    if failing_step not in FAILING_STEPS:
        raise TraceExportError("failing_step must be one of: retrieval, processing, generation")
    validate_trace(trace)
    timestamp = created_at or utc_now()
    cid = case_id or default_case_id(source_file=source_file, failing_step=failing_step)
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": cid,
        "title": title or f"Regression trace for {source_file}",
        "created_at": timestamp,
        "source": {
            "source_file": source_file,
            "status": status,
            "error_type": error_type,
            "description": description,
        },
        "failing_step": failing_step,
        "expected_output": expected_output,
        "aie_required_fields": list(AIE_REQUIRED_FIELDS),
        "trace": dict(trace),
    }


def export_failed_run(
    project_root: Path,
    *,
    trace: Mapping[str, Any],
    failing_step: str,
    expected_output: Any,
    source_file: str,
    error_type: str,
    description: str,
    status: str = "failed",
    case_id: str | None = None,
    title: str | None = None,
    corpus_dir: Path | None = None,
) -> Path:
    """Write a failed run trace into the eval-spec regression corpus."""
    root = Path(project_root)
    destination = Path(corpus_dir) if corpus_dir is not None else root / "eval-specs" / "regression-traces"
    case = build_case(
        trace=trace,
        failing_step=failing_step,
        expected_output=expected_output,
        source_file=source_file,
        error_type=error_type,
        description=description,
        status=status,
        case_id=case_id,
        title=title,
    )
    path = destination / f"{_slug(case['case_id'])}.json"
    _atomic_write_json(path, case)
    return path


def auto_export_from_failure(
    project_root: Path,
    *,
    source_file: str,
    error_type: str,
    description: str,
    details: Mapping[str, Any] | None = None,
    status: str = "failed",
) -> Path | None:
    """
    Export a regression case from a failure event when trace details are present.

    Expected ``details`` shape:
    ``{"trace_export": {"trace": {...}, "failing_step": "...", "expected_output": ...}}``.
    Missing ``trace_export`` means the caller had no replayable trace, so no empty
    case is fabricated.
    """
    if not isinstance(details, Mapping):
        return None
    payload = details.get("trace_export")
    if not isinstance(payload, Mapping):
        return None
    trace = _require_mapping(payload.get("trace"), "details.trace_export.trace")
    return export_failed_run(
        project_root,
        trace=trace,
        failing_step=str(payload.get("failing_step", "")),
        expected_output=payload.get("expected_output"),
        source_file=source_file,
        error_type=error_type,
        description=description,
        status=status,
        case_id=payload.get("case_id") if isinstance(payload.get("case_id"), str) else None,
        title=payload.get("title") if isinstance(payload.get("title"), str) else None,
    )


def load_case(case_path: Path) -> dict[str, Any]:
    data = json.loads(Path(case_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TraceExportError("case file must contain a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise TraceExportError(f"unsupported schema_version: {data.get('schema_version')}")
    if data.get("failing_step") not in FAILING_STEPS:
        raise TraceExportError("case has invalid failing_step")
    validate_trace(_require_mapping(data.get("trace"), "case.trace"))
    return data


def replay_case(case_path: Path, *, actual_output: Any | None = None) -> dict[str, Any]:
    """
    Run the minimal regression check for an exported case.

    Passing ``actual_output`` represents the fixed system output. Without it, the
    captured failing output is replayed, which should usually fail.
    """
    case = load_case(case_path)
    observed = case["trace"]["output"] if actual_output is None else actual_output
    passed = observed == case["expected_output"]
    return {
        "case_id": case["case_id"],
        "status": "pass" if passed else "fail",
        "failing_step": case["failing_step"],
        "expected_output": case["expected_output"],
        "actual_output": observed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or replay exported regression trace cases")
    sub = parser.add_subparsers(dest="command", required=True)
    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("case")
    replay_cmd = sub.add_parser("replay")
    replay_cmd.add_argument("case")
    replay_cmd.add_argument("--actual-output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        load_case(Path(args.case))
        print(f"valid regression trace case: {args.case}")
        return 0
    if args.command == "replay":
        result = replay_case(Path(args.case), actual_output=args.actual_output)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "pass" else 1
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
