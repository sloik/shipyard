#!/usr/bin/env python3
"""SPEC-052: Verification report artifact helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEVERITIES = {"CRITICAL", "WARNING", "SUGGESTION"}
DIMENSIONS = {"completeness", "correctness", "coherence"}
FINAL_ASSESSMENTS = {"pass", "pass_with_warnings", "fail"}

# This is the only generated artifact that an independent verifier may ignore
# when asserting its read-only Git footprint.  Keep the policy exact: a broad
# ``graphify-out/`` exclusion would hide verifier writes to other artifacts.
VERIFIER_FOOTPRINT_EXCLUSIONS = frozenset({"graphify-out/graph.html"})
VERIFIER_REPORT_ROOTS = ("reports/", ".nightshift/reports/", "canonical/reports/")
VERIFIER_VERDICT_REQUIRED_KEYS = frozenset({
    "spec_id", "branch", "baseline_commit", "head_commit", "verdict",
    "acs", "suites", "git_footprint", "contamination",
})


class VerifierSurfacePreparationError(RuntimeError):
    """Controlled pre-dispatch failure; the harness must launch no verifier."""


@dataclass(frozen=True)
class PreparedVerifierDispatch:
    """Validated private preparation state for one harness dispatch.

    ``evidence`` remains parent-owned.  Only :meth:`public_plan` may cross the
    harness boundary, which deliberately omits the source repository, report
    paths, and parent-owned evidence path.
    """

    repository: Path
    evidence_path: Path
    evidence: dict[str, Any]
    evidence_sha256: str
    suite_commands: tuple[str, ...]

    def public_plan(self) -> dict[str, Any]:
        commits = self.evidence["surface_commits"]
        return {
            "schema_version": "1.0.0",
            "surface_kind": "standalone-sanitized-git",
            "repository": str(self.repository),
            "baseline_ref": "verifier-baseline",
            "head_ref": "verifier-head",
            "baseline_commit": commits["baseline"],
            "head_commit": commits["head"],
            "brief_kind": "normal" if self.suite_commands else "no-test-suite",
            "suite_commands": list(self.suite_commands),
            "containment_evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True)
class GitFootprint:
    """A read-only snapshot of the worktree assigned to a verifier.

    The caller supplies the worktree under test.  Deliberately accepting no
    parent-checkout argument prevents a dirty coordinator checkout from
    contaminating the verifier's footprint decision.
    """

    tree: str
    porcelain: str


def _run_git(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        text=True,
        capture_output=True,
        check=False,
        env=_git_environment(),
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _git_bytes(repository: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, check=False,
        env=_git_environment(),
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.decode("utf-8", "replace").strip()
            or f"git {' '.join(args)} failed"
        )
    return result.stdout


def _git_environment(**extra: str) -> dict[str, str]:
    """Return a deterministic Git environment without ambient repository links."""
    blocked = {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_INDEX_FILE",
    }
    return {**{key: value for key, value in os.environ.items() if key not in blocked}, **extra}


def _normalise_repo_path(path: str) -> str:
    normalised = path.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    if not normalised or normalised.startswith("/") or ".." in Path(normalised).parts:
        raise ValueError(f"unsafe repository path: {path!r}")
    return normalised


def is_verifier_report_path(path: str, *, explicit: Iterable[str] = ()) -> bool:
    """Return whether a tracked path carries worker/verifier conclusions."""
    normalised = _normalise_repo_path(path)
    exact = {_normalise_repo_path(item) for item in explicit}
    return normalised in exact or normalised.startswith(VERIFIER_REPORT_ROOTS)


def _clear_snapshot(destination: Path) -> None:
    for child in destination.iterdir():
        if child.name == ".git":
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)


def _materialize_ref(
    source_repository: Path,
    destination: Path,
    ref: str,
    *,
    report_paths: Iterable[str],
) -> list[str]:
    """Materialize one tracked snapshot without sharing the source object DB."""
    _clear_snapshot(destination)
    excluded: list[str] = []
    entries = _git_bytes(source_repository, "ls-tree", "-rz", ref).split(b"\0")
    for raw in entries:
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        path = _normalise_repo_path(raw_path.decode("utf-8", "surrogateescape"))
        if is_verifier_report_path(path, explicit=report_paths):
            excluded.append(path)
            continue
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError(f"unsupported tracked entry for verifier surface: {path} ({mode} {kind})")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _git_bytes(source_repository, "cat-file", "blob", object_id)
        if mode == "120000":
            link = body.decode("utf-8", "surrogateescape")
            resolved = (target.parent / link).resolve()
            if Path(os.path.commonpath((destination.resolve(), resolved))) != destination.resolve():
                raise ValueError(f"symlink escapes verifier surface: {path}")
            target.symlink_to(link)
        else:
            target.write_bytes(body)
            target.chmod(0o755 if mode == "100755" else 0o644)
    return sorted(excluded)


def prepare_verifier_surface(
    source_repository: Path,
    destination: Path,
    *,
    baseline_ref: str,
    head_ref: str,
    report_paths: Iterable[str],
    evidence_path: Path,
) -> dict[str, Any]:
    """Build the sole verifier surface as a standalone, report-free Git repo.

    A linked worktree is deliberately rejected as the destination: worktrees
    share the source object database and therefore leave excluded report blobs
    reachable through Git even when absent from the checkout.
    """
    source_repository = source_repository.resolve()
    destination = destination.resolve()
    report_paths = tuple(report_paths)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("verifier surface destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    source_common = Path(_run_git(source_repository, "rev-parse", "--git-common-dir").strip())
    if not source_common.is_absolute():
        source_common = (source_repository / source_common).resolve()
    subprocess.run(
        ["git", "init", "-q", str(destination)], check=True, env=_git_environment()
    )
    target_common = Path(_run_git(destination, "rev-parse", "--git-common-dir").strip())
    if not target_common.is_absolute():
        target_common = (destination / target_common).resolve()
    if target_common.resolve() == source_common.resolve():
        raise ValueError("verifier surface may not share the source Git object database")
    _run_git(destination, "config", "user.name", "Nightshift verifier surface")
    _run_git(destination, "config", "user.email", "verifier@example.invalid")
    refs = (("baseline", baseline_ref), ("head", head_ref))
    commits: dict[str, str] = {}
    excluded_by_ref: dict[str, list[str]] = {}
    fixed_env = _git_environment(
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    for label, ref in refs:
        excluded_by_ref[label] = _materialize_ref(
            source_repository, destination, ref, report_paths=report_paths
        )
        _run_git(destination, "add", "-A")
        result = subprocess.run(
            ["git", "-C", str(destination), "commit", "--allow-empty", "-qm", f"verifier {label} snapshot"],
            env=fixed_env, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"could not commit {label} snapshot")
        commits[label] = _run_git(destination, "rev-parse", "HEAD").strip()
        _run_git(destination, "tag", f"verifier-{label}")

    probes = []
    for path in sorted({_normalise_repo_path(item) for item in report_paths}):
        for label in ("baseline", "head"):
            probe = subprocess.run(
                ["git", "-C", str(destination), "cat-file", "-e", f"verifier-{label}:{path}"],
                capture_output=True, check=False, env=_git_environment(),
            )
            probes.append({"ref": label, "path": path, "unreachable": probe.returncode != 0})
    if not probes or not all(probe["unreachable"] for probe in probes):
        raise RuntimeError("worker report remains reachable from verifier surface")
    evidence = {
        "schema_version": "1.0.0",
        "surface_kind": "standalone-sanitized-git",
        "source_refs": {"baseline": baseline_ref, "head": head_ref},
        "surface_commits": commits,
        "excluded_paths": excluded_by_ref,
        "report_reachability": probes,
        "shared_object_database": False,
        "head_tree": _run_git(destination, "rev-parse", "HEAD^{tree}").strip(),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def prepare_verifier_dispatch(
    source_repository: Path,
    destination: Path,
    *,
    baseline_ref: str,
    head_ref: str,
    report_paths: Iterable[str],
    evidence_path: Path,
    suite_commands: Iterable[str] = (),
) -> PreparedVerifierDispatch:
    """Prepare the sole verifier surface and emit a sanitized launch plan.

    Normal and no-test-suite routes call this same boundary.  The durable
    evidence is reloaded and independently checked before a plan exists, so a
    preparation or reachability failure cannot degrade to the source worktree.
    """
    try:
        source_repository = source_repository.resolve()
        destination = destination.resolve()
        normalized_reports = tuple(sorted({_normalise_repo_path(path) for path in report_paths}))
        suites = tuple(suite_commands)
        if (
            destination == source_repository
            or destination.is_relative_to(source_repository)
            or source_repository.is_relative_to(destination)
        ):
            raise ValueError("verifier surface must be outside the source repository")
        if not all(isinstance(command, str) and command.strip() for command in suites):
            raise ValueError("suite commands must be non-empty strings")
        source_text = str(source_repository)
        if any(
            source_text in command
            or any(report_path in command for report_path in normalized_reports)
            for command in suites
        ):
            raise ValueError("suite command discloses the source repository or report path")
        evidence = prepare_verifier_surface(
            source_repository,
            destination,
            baseline_ref=baseline_ref,
            head_ref=head_ref,
            report_paths=normalized_reports,
            evidence_path=evidence_path,
        )
        evidence_bytes = evidence_path.read_bytes()
        durable_evidence = json.loads(evidence_bytes)
        probes = durable_evidence.get("report_reachability")
        expected_probes = {
            (label, report_path)
            for report_path in normalized_reports
            for label in ("baseline", "head")
        }
        observed_probes = {
            (probe.get("ref"), probe.get("path"))
            for probe in probes
            if isinstance(probe, dict) and probe.get("unreachable") is True
        } if isinstance(probes, list) else set()
        commits = durable_evidence.get("surface_commits")
        ready = (
            durable_evidence == evidence
            and bool(normalized_reports)
            and durable_evidence.get("surface_kind") == "standalone-sanitized-git"
            and durable_evidence.get("shared_object_database") is False
            and observed_probes == expected_probes
            and isinstance(commits, dict)
            and set(commits) == {"baseline", "head"}
            and _run_git(destination, "rev-parse", "verifier-baseline").strip() == commits["baseline"]
            and _run_git(destination, "rev-parse", "verifier-head").strip() == commits["head"]
        )
    except Exception as exc:
        raise VerifierSurfacePreparationError("verifier surface preparation failed") from exc

    if not ready:
        raise VerifierSurfacePreparationError("verifier surface reachability assertion failed")
    return PreparedVerifierDispatch(
        repository=destination,
        evidence_path=evidence_path.resolve(),
        evidence=durable_evidence,
        evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        suite_commands=suites,
    )


def validate_verifier_verdict_dict(data: dict[str, Any]) -> list[str]:
    """Validate the independent-verifier envelope fields owned by the kit."""
    errors = [f"missing top-level key '{key}'" for key in sorted(VERIFIER_VERDICT_REQUIRED_KEYS - data.keys())]
    if data.get("verdict") not in {"pass", "fail", "disputes_premise"}:
        errors.append(f"verdict not in enum: {data.get('verdict')!r}")
    return errors


def verifier_surface_self_test() -> dict[str, Any]:
    """Managed release smoke contract for containment and verdict semantics."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "source"
        surface = root / "surface"
        no_suite_surface = root / "surface-no-suite"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        _run_git(source, "config", "user.name", "Nightshift smoke")
        _run_git(source, "config", "user.email", "smoke@example.invalid")
        (source / "code.py").write_text("VALUE = 1\n", encoding="utf-8")
        _run_git(source, "add", "code.py")
        _run_git(source, "commit", "-qm", "baseline")
        baseline = _run_git(source, "rev-parse", "HEAD").strip()
        report = source / "canonical/reports/nightshift-report.md"
        report.parent.mkdir(parents=True)
        report.write_text("worker conclusion\n", encoding="utf-8")
        (source / "code.py").write_text("VALUE = 2\n", encoding="utf-8")
        _run_git(source, "add", "-A")
        _run_git(source, "commit", "-qm", "head")
        head = _run_git(source, "rev-parse", "HEAD").strip()
        prepared = prepare_verifier_dispatch(
            source, surface, baseline_ref=baseline, head_ref=head,
            report_paths=["canonical/reports/nightshift-report.md"],
            evidence_path=root / "containment.json",
            suite_commands=["python -m pytest -q"],
        )
        no_suite = prepare_verifier_dispatch(
            source, no_suite_surface, baseline_ref=baseline, head_ref=head,
            report_paths=["canonical/reports/nightshift-report.md"],
            evidence_path=root / "containment-no-suite.json",
        )
        plan = prepared.public_plan()
        no_suite_plan = no_suite.public_plan()
        forbidden_values = {str(source.resolve()), "canonical/reports/nightshift-report.md"}
        serialized_plans = json.dumps([plan, no_suite_plan], sort_keys=True)
        if any(value in serialized_plans for value in forbidden_values):
            raise RuntimeError("dispatch plan disclosed source repository or report path")
        if (
            plan["repository"] != str(surface.resolve())
            or plan["brief_kind"] != "normal"
            or no_suite_plan["repository"] != str(no_suite_surface.resolve())
            or no_suite_plan["brief_kind"] != "no-test-suite"
            or no_suite_plan["suite_commands"]
        ):
            raise RuntimeError("normal/no-test-suite dispatch plan contract failed")
        evidence = prepared.evidence
        verdict = {
            "spec_id": "SMOKE", "branch": "smoke", "baseline_commit": baseline,
            "head_commit": head, "verdict": "pass", "acs": [{"id": "AC1", "status": "pass", "evidence": "smoke"}],
            "suites": [], "git_footprint": {"tree_before": evidence["head_tree"], "tree_after": evidence["head_tree"], "porcelain": ""},
        }
        missing_errors = validate_verifier_verdict_dict(verdict)
        verdict["contamination"] = None
        if not missing_errors or validate_verifier_verdict_dict(verdict):
            raise RuntimeError("verifier verdict contamination contract failed")
        return evidence


def capture_verifier_footprint(worktree: Path) -> GitFootprint:
    """Capture the verifier footprint from its assigned worktree only."""
    return GitFootprint(
        tree=_run_git(worktree, "rev-parse", "HEAD^{tree}").strip(),
        porcelain=_run_git(worktree, "status", "--porcelain=v1", "--untracked-files=all"),
    )


def is_excluded_verifier_footprint_path(path: str) -> bool:
    """Return whether *path* is the one allowed generated-file artifact."""
    return path.replace("\\", "/") in VERIFIER_FOOTPRINT_EXCLUSIONS


def verifier_footprint_errors(before: GitFootprint, after: GitFootprint) -> list[str]:
    """Validate a verifier's worktree-local, read-only Git footprint."""
    errors: list[str] = []
    if before.tree != after.tree:
        errors.append(f"verifier mutated the repo tree: {before.tree} -> {after.tree}")
    dirty_paths = [
        line[3:]
        for line in after.porcelain.splitlines()
        if line.strip() and not is_excluded_verifier_footprint_path(line[3:])
    ]
    if dirty_paths:
        errors.append("verifier left the worktree dirty: " + "; ".join(dirty_paths))
    return errors


def acceptance_criterion_ids(spec_text: str) -> set[str]:
    """Extract AC IDs from this spec's Acceptance Criteria section only."""
    section = re.search(
        r"^##\s+Acceptance Criteria\s*$(.*?)(?=^##\s|\Z)",
        spec_text,
        re.MULTILINE | re.DOTALL,
    )
    return set(re.findall(r"\bAC\d+\b", section.group(1) if section else ""))


def uncovered_acceptance_criteria(spec_text: str, reported_ids: Iterable[str]) -> list[str]:
    """Return current-spec AC IDs absent from a verifier's per-AC evidence."""
    return sorted(acceptance_criterion_ids(spec_text) - set(reported_ids))


def verifier_worktree_boundary(worktree: Path) -> str:
    """Canonical wording for the parent/verifier isolation boundary."""
    return (
        f"Run every read-only Git footprint command against the assigned worktree "
        f"({worktree}), never the parent or coordinator checkout. Parent-checkout "
        "dirtiness is outside the verifier footprint."
    )


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
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv and not raw_argv[0].startswith("-") and raw_argv[0] not in {
        "prepare-dispatch",
        "prepare-surface",
        "verifier-self-test",
    }:
        data = load_report(Path(raw_argv[0]))
        errors = validate_report_dict(data)
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            return 1
        print(render_markdown(data))
        return 0
    parser = argparse.ArgumentParser(description="Nightshift verification helpers")
    subparsers = parser.add_subparsers(dest="command")
    prepare = subparsers.add_parser("prepare-surface")
    prepare.add_argument("--source", required=True, type=Path)
    prepare.add_argument("--destination", required=True, type=Path)
    prepare.add_argument("--baseline", required=True)
    prepare.add_argument("--head", required=True)
    prepare.add_argument("--report-path", action="append", required=True)
    prepare.add_argument("--evidence", required=True, type=Path)
    dispatch = subparsers.add_parser("prepare-dispatch")
    dispatch.add_argument("--source", required=True, type=Path)
    dispatch.add_argument("--destination", required=True, type=Path)
    dispatch.add_argument("--baseline", required=True)
    dispatch.add_argument("--head", required=True)
    dispatch.add_argument("--report-path", action="append", required=True)
    dispatch.add_argument("--evidence", required=True, type=Path)
    dispatch.add_argument("--suite-command", action="append", default=[])
    subparsers.add_parser("verifier-self-test")
    args = parser.parse_args(raw_argv)
    if args.command == "prepare-surface":
        prepare_verifier_surface(
            args.source, args.destination, baseline_ref=args.baseline,
            head_ref=args.head, report_paths=args.report_path, evidence_path=args.evidence,
        )
        return 0
    if args.command == "prepare-dispatch":
        try:
            prepared = prepare_verifier_dispatch(
                args.source, args.destination, baseline_ref=args.baseline,
                head_ref=args.head, report_paths=args.report_path,
                evidence_path=args.evidence, suite_commands=args.suite_command,
            )
        except VerifierSurfacePreparationError:
            print(json.dumps({
                "status": "evidence_gap",
                "controller_reason": "verifier_surface_unavailable",
            }, sort_keys=True), file=sys.stderr)
            return 2
        print(json.dumps(prepared.public_plan(), sort_keys=True))
        return 0
    if args.command == "verifier-self-test":
        verifier_surface_self_test()
        return 0
    parser.error("a report path or subcommand is required")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
