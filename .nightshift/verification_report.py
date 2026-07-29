#!/usr/bin/env python3
"""SPEC-052: Verification report artifact helpers."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SEVERITIES = {"CRITICAL", "WARNING", "SUGGESTION"}
DIMENSIONS = {"completeness", "correctness", "coherence"}
FINAL_ASSESSMENTS = {"pass", "pass_with_warnings", "fail"}


@dataclass
class VerificationIssue:
    severity: str
    dimension: str
    summary: str
    evidence: str
    recommendation: str
    file: str | None = None
    line: int | None = None
    rationale: str | None = None
    follow_up: str | None = None

    def validate(self) -> list[str]:
        errors = []
        if self.severity not in SEVERITIES:
            errors.append(f"invalid severity: {self.severity}")
        if self.dimension not in DIMENSIONS:
            errors.append(f"invalid dimension: {self.dimension}")
        for field_name in ("summary", "evidence", "recommendation"):
            if not getattr(self, field_name):
                errors.append(f"missing issue field: {field_name}")
        if self.severity == "WARNING" and not (self.rationale or self.follow_up):
            errors.append("WARNING issue requires rationale or follow_up")
        return errors


@dataclass
class VerificationReport:
    spec_id: str
    generated_at: str
    dimensions: dict[str, dict[str, Any]]
    issues: list[VerificationIssue] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    tool: str = "nightshift"
    model: str | None = None
    skipped_checks: list[dict[str, str]] = field(default_factory=list)

    @property
    def final_assessment(self) -> str:
        if any(issue.severity == "CRITICAL" for issue in self.issues):
            return "fail"
        if any(issue.severity == "WARNING" for issue in self.issues):
            return "pass_with_warnings"
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [asdict(issue) for issue in self.issues]
        data["final_assessment"] = self.final_assessment
        return data


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_report(spec_id: str, *, issues: Iterable[VerificationIssue] = (), commands_run: list[dict[str, Any]] | None = None, dimensions: dict[str, dict[str, Any]] | None = None, skipped_checks: list[dict[str, str]] | None = None) -> VerificationReport:
    base_dimensions = {
        "completeness": {"status": "pass", "summary": "No completeness issues found."},
        "correctness": {"status": "pass", "summary": "No correctness issues found."},
        "coherence": {"status": "pass", "summary": "No coherence issues found."},
    }
    if dimensions:
        base_dimensions.update(dimensions)
    issue_list = list(issues)
    for issue in issue_list:
        if issue.severity == "CRITICAL":
            base_dimensions[issue.dimension]["status"] = "fail"
        elif issue.severity == "WARNING" and base_dimensions[issue.dimension].get("status") != "fail":
            base_dimensions[issue.dimension]["status"] = "warning"
    return VerificationReport(
        spec_id=spec_id,
        generated_at=now_iso(),
        dimensions=base_dimensions,
        issues=issue_list,
        commands_run=commands_run or [],
        skipped_checks=skipped_checks or [],
    )


def validate_report_dict(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("spec_id", "generated_at", "dimensions", "issues", "commands_run", "final_assessment"):
        if key not in data:
            errors.append(f"missing required key: {key}")
    if data.get("final_assessment") not in FINAL_ASSESSMENTS:
        errors.append(f"invalid final_assessment: {data.get('final_assessment')}")
    dimensions = data.get("dimensions") or {}
    for dim in DIMENSIONS:
        if dim not in dimensions:
            errors.append(f"missing dimension: {dim}")
    for idx, raw in enumerate(data.get("issues") or []):
        try:
            issue = VerificationIssue(**{k: raw.get(k) for k in VerificationIssue.__dataclass_fields__})
        except TypeError as exc:
            errors.append(f"issue {idx} malformed: {exc}")
            continue
        errors.extend(f"issue {idx}: {err}" for err in issue.validate())
    if data.get("final_assessment") == "fail" and not any((i or {}).get("severity") == "CRITICAL" for i in data.get("issues") or []):
        errors.append("final_assessment fail requires at least one CRITICAL issue")
    return errors


def render_markdown(data: dict[str, Any]) -> str:
    lines = [f"# Verification Report: {data.get('spec_id', 'UNKNOWN')}", ""]
    lines.append("## Summary")
    lines.append("")
    lines.append("| Dimension | Status | Summary |")
    lines.append("|---|---|---|")
    for dim in ("completeness", "correctness", "coherence"):
        info = (data.get("dimensions") or {}).get(dim, {})
        lines.append(f"| {dim.title()} | {info.get('status', 'unknown')} | {info.get('summary', '')} |")
    lines.append("")
    lines.append(f"Final assessment: **{data.get('final_assessment', 'unknown')}**")
    for severity in ("CRITICAL", "WARNING", "SUGGESTION"):
        lines += ["", f"## {severity}"]
        issues = [i for i in data.get("issues", []) if i.get("severity") == severity]
        if not issues:
            lines.append("None.")
            continue
        for issue in issues:
            loc = f" ({issue.get('file')}:{issue.get('line')})" if issue.get("file") and issue.get("line") else ""
            lines.append(f"- **{issue.get('dimension')}**: {issue.get('summary')}{loc}")
            lines.append(f"  Evidence: {issue.get('evidence')}")
            lines.append(f"  Recommendation: {issue.get('recommendation')}")
            if issue.get("rationale"):
                lines.append(f"  Rationale: {issue.get('rationale')}")
            if issue.get("follow_up"):
                lines.append(f"  Follow-up: {issue.get('follow_up')}")
    lines += ["", "## Commands Run"]
    if not data.get("commands_run"):
        lines.append("None recorded.")
    for command in data.get("commands_run", []):
        lines.append(f"- `{command.get('command')}` -> exit {command.get('exit_code')}: {command.get('summary', '')}")
    if data.get("skipped_checks"):
        lines += ["", "## Skipped Checks"]
        for skipped in data["skipped_checks"]:
            lines.append(f"- {skipped.get('name')}: {skipped.get('reason')}")
    return "\n".join(lines) + "\n"


def write_report(report: VerificationReport, reports_root: Path) -> tuple[Path, Path]:
    report_dir = reports_root / report.spec_id
    report_dir.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    json_path = report_dir / "verification.json"
    md_path = report_dir / "verification.md"
    tmp_json = json_path.with_suffix(".json.tmp")
    tmp_md = md_path.with_suffix(".md.tmp")
    tmp_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_md.write_text(render_markdown(data), encoding="utf-8")
    os.replace(tmp_json, json_path)
    os.replace(tmp_md, md_path)
    return json_path, md_path


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def completion_gate(report_json: Path, *, override_reason_file: Path | None = None) -> tuple[bool, list[str]]:
    if not report_json.exists():
        return False, [f"verification report missing: {report_json}"]
    data = load_report(report_json)
    errors = validate_report_dict(data)
    if errors:
        return False, errors
    if data.get("final_assessment") == "fail":
        critical = [i.get("summary", "critical issue") for i in data.get("issues", []) if i.get("severity") == "CRITICAL"]
        return False, ["verification has CRITICAL issue(s): " + "; ".join(critical)]
    warnings = [i for i in data.get("issues", []) if i.get("severity") == "WARNING" and not (i.get("rationale") or i.get("follow_up"))]
    if warnings:
        return False, ["WARNING issue lacks rationale/follow_up: " + warnings[0].get("summary", "warning")]
    if data.get("final_assessment") == "pass_with_warnings" and override_reason_file and not override_reason_file.exists():
        return False, [f"warning acceptance requires override reason file: {override_reason_file}"]
    return True, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Nightshift verification reports")
    parser.add_argument("report_json")
    args = parser.parse_args(argv)
    data = load_report(Path(args.report_json))
    errors = validate_report_dict(data)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(render_markdown(data))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main())
