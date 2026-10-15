#!/usr/bin/env python3
"""Project-configured terminal outcome record validation (SPEC-224).

The commit-msg hook invokes this module only when a project opts in with an
``terminal_outcomes`` mapping.  The mapping owns both the storage adapter and
field names, so canonical code never assumes an Argo-specific ledger.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

FLEET_FIELDS = ("spec_id", "terminal_outcome", "agent_response", "causal_confidence", "human_action_needed", "evidence_refs")
AGENT_OUTCOME_FIELDS = (
    "schema_version", "spec_id", "run_id", "role", "agent_outcome", "reason",
    "head_digest", "artifact_refs", "idempotency_key", "attempt_ordinal",
    "duration_s", "terminal_outcome", "human_action_required", "next_action",
    "recovery_source", "diagnosis_class", "causal_confidence",
    "candidate_preserved", "repair_route", "diagnostician_allowance",
    "repair_allowance", "operator_action", "delivery_phase",
)
# SPEC-NS-KIT-002-001 R4: optional additive tag naming the project that produced a row,
# so fleet analysis never has to infer it from the file's location. Producers that
# emit the closed field set above stay valid; the tag is added at encoding time.
OPTIONAL_AGENT_FIELDS = ("project",)
PROJECT_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
AGENT_FIELD_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")
FORBIDDEN_AGENT_FIELD_RE = re.compile(
    r"(?:password|passwd|secret|credential|token|prompt|log|url|path|username|environment)",
    re.IGNORECASE,
)


def _agent_field_mapping(config: dict[str, Any]) -> dict[str, str]:
    """Return one collision-free, privacy-safe canonical-to-adapter mapping."""
    raw = config.get("agent_fields", {})
    if not isinstance(raw, dict):
        raise TypeError("terminal_outcomes.agent_fields must be a mapping")
    unknown = set(raw) - set(AGENT_OUTCOME_FIELDS) - set(OPTIONAL_AGENT_FIELDS)
    if unknown:
        raise ValueError(f"unknown canonical agent fields: {sorted(unknown)}")
    mapping: dict[str, str] = {}
    for canonical in (*AGENT_OUTCOME_FIELDS, *OPTIONAL_AGENT_FIELDS):
        output = raw.get(canonical, canonical)
        if (
            not isinstance(output, str)
            or not AGENT_FIELD_NAME_RE.fullmatch(output)
            or FORBIDDEN_AGENT_FIELD_RE.search(output)
        ):
            raise ValueError(f"unsafe adapter output field for {canonical}")
        mapping[canonical] = output
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("agent field mapping contains output collisions")
    return mapping


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file() or yaml is None:
        return {}
    try:
        merged: dict[str, Any] = {}
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(document, dict):
                merged.update(document)
        value = merged.get("terminal_outcomes", {})
        return value if isinstance(value, dict) else {}
    except yaml.YAMLError:
        return {}


def configured(config: dict[str, Any]) -> bool:
    return bool(config.get("enabled", False))


def _rows(adapter: str, raw: str) -> list[dict[str, Any]]:
    if adapter == "json-array":
        value = json.loads(raw)
        if not isinstance(value, list):
            raise ValueError("json-array adapter requires a JSON array")
        return [row for row in value if isinstance(row, dict)]
    if adapter == "jsonl":
        return [value for line in raw.splitlines() if line.strip() for value in [json.loads(line)] if isinstance(value, dict)]
    raise ValueError(f"unsupported terminal outcome adapter: {adapter}")


def read_records(path: Path, adapter: str) -> list[dict[str, Any]]:
    return _rows(adapter, path.read_text(encoding="utf-8"))


def normalized(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    fields = config.get("fields", {})
    fields = fields if isinstance(fields, dict) else {}
    return {canonical: record.get(str(fields.get(canonical, canonical))) for canonical in FLEET_FIELDS}


def _project_tag(value: Any) -> str:
    if not isinstance(value, str) or not PROJECT_TAG_RE.fullmatch(value):
        raise ValueError("project tag must be a short plain project name")
    if FORBIDDEN_AGENT_FIELD_RE.search(value):
        raise ValueError("project tag must be a short plain project name")
    return value


def configured_agent_outcome(
    record: dict[str, Any], config: dict[str, Any], project: str | None = None
) -> dict[str, Any]:
    """Map one closed SPEC-235 record through the existing adapter configuration.

    The closed field set is unchanged; an optional `project` tag (record value,
    else `project` argument, else config `project`) is added when determinable
    and never invented when it is not.
    """
    if set(record) - set(OPTIONAL_AGENT_FIELDS) != set(AGENT_OUTCOME_FIELDS):
        raise ValueError("agent outcome fields do not match the closed schema")
    fields = _agent_field_mapping(config)
    mapped = {fields[name]: record[name] for name in AGENT_OUTCOME_FIELDS}
    tag = record.get("project")
    if tag is None:
        tag = project if project is not None else config.get("project")
    if tag is not None:
        mapped[fields["project"]] = _project_tag(tag)
    return mapped


def normalized_agent_outcome(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Normalize either configured adapter shape back to provider-neutral fields."""
    fields = _agent_field_mapping(config)
    result = {name: record.get(fields[name]) for name in AGENT_OUTCOME_FIELDS}
    if fields["project"] in record:
        result["project"] = record[fields["project"]]
    return result


def encode_agent_outcomes(
    records: list[dict[str, Any]], config: dict[str, Any], project: str | None = None
) -> str:
    """Encode records with the configured SPEC-224 json-array or jsonl adapter."""
    mapped = [configured_agent_outcome(record, config, project) for record in records]
    adapter = str(config.get("adapter", "json-array"))
    if adapter == "json-array":
        return json.dumps(mapped, sort_keys=True, separators=(",", ":")) + "\n"
    if adapter == "jsonl":
        return "".join(
            json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
            for item in mapped
        )
    raise ValueError(f"unsupported terminal outcome adapter: {adapter}")


def conforming(record: dict[str, Any], spec_id: str, terminal: str, config: dict[str, Any]) -> bool:
    row = normalized(record, config)
    required = config.get("required_fields", list(FLEET_FIELDS))
    if not isinstance(required, list):
        return False
    return (
        row["spec_id"] == spec_id
        and row["terminal_outcome"] == terminal
        and all(row.get(str(field)) not in (None, "", []) for field in required)
    )


def staged_records(repo: Path, relative_path: str, adapter: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def show(ref: str) -> list[dict[str, Any]]:
        result = subprocess.run(["git", "-C", str(repo), "show", ref], text=True, capture_output=True, check=False)
        if result.returncode:
            return []
        return _rows(adapter, result.stdout)
    return show(f"HEAD:{relative_path}"), show(f":{relative_path}")


def changed_matching_record(repo: Path, spec_id: str, terminal: str, config: dict[str, Any]) -> tuple[bool, str]:
    path = config.get("path")
    adapter = config.get("adapter", "json-array")
    if not isinstance(path, str) or not path.strip():
        return False, "terminal_outcomes.path is required when enforcement is enabled"
    if adapter not in {"json-array", "jsonl"}:
        return False, "terminal_outcomes.adapter must be json-array or jsonl"
    try:
        before, after = staged_records(repo, path, adapter)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"cannot read staged terminal outcome records: {exc}"
    # A multiset difference treats both insertion and in-place replacement as a
    # changed record, while preserving legitimate duplicate records.
    before_counts = Counter(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in before)
    for row in after:
        key = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if before_counts[key]:
            before_counts[key] -= 1
            continue
        if conforming(row, spec_id, terminal, config):
            return True, "matching changed terminal outcome record staged"
    return False, f"no changed conforming terminal outcome record for {spec_id} ({terminal})"


def aggregate(paths: list[Path], config: dict[str, Any]) -> list[dict[str, Any]]:
    adapter = str(config.get("adapter", "json-array"))
    return [normalized(record, config) for path in paths for record in read_records(path, adapter)]


def assessed_block_interpretation(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    """Interpret the existing closed adapter record without calling a parent block delivery."""
    row = normalized_agent_outcome(record, config)
    if (row.get("role") != "parent" or row.get("agent_outcome") != "blocked"
            or row.get("terminal_outcome") != "blocked" or row.get("recovery_source") != "implementer_blocked"
            or row.get("delivery_phase") != "terminal_blocked" or row.get("candidate_preserved") is not True
            or not row.get("diagnosis_class")):
        return None
    return {"resolution_kind": "implementer-assessed-blocked", "attempt_outcome": "blocked",
            "parent_outcome": "blocked", "verified_delivery": False, "verifier_dispatches": 0,
            "verifier_samples": 0, "spec_id": row["spec_id"], "run_id": row["run_id"]}


def check_assessment_resolution(repo: Path, message: str) -> tuple[bool, str]:
    """Normal hook: verify exact staged reducer proof and preserved candidate branch."""
    from verifier_feedback import feedback_state_from_dict, implementer_assessment_terminal_evidence
    try:
        subject = message.splitlines()[0]
        match = re.fullmatch(r"chore: mark (\S+) blocked", subject)
        if not match:
            raise ValueError("implementer-assessed-blocked is blocked-only")
        entries = re.findall(r"^(Nightshift-[A-Za-z0-9-]+):[ \t]*(.*)$", message, re.M)
        trailers = dict(entries)
        if len(entries) != len(trailers):
            raise ValueError("duplicate terminal evidence trailers")
        if (trailers.get("Nightshift-Resolution-Kind") != "implementer-assessed-blocked"
                or trailers.get("Nightshift-Evidence-Verifier") != "absent"
                or trailers.get("Nightshift-Evidence-ACs") != "unknown"):
            raise ValueError("assessment cannot claim a verifier or accepted ACs")
        relative = trailers.get("Nightshift-Evidence-Assessment", "")
        path = PurePosixPath(relative)
        if not relative or path.is_absolute() or ".." in path.parts or str(path) != relative:
            raise ValueError("unsafe or missing staged assessment reference")
        staged = subprocess.run(["git", "-C", str(repo), "show", f":{relative}"], capture_output=True)
        data = staged.stdout
        if staged.returncode or len(data) > 131072:
            raise ValueError("staged assessment unavailable or oversized")
        if hashlib.sha256(data).hexdigest() != trailers.get("Nightshift-Evidence-Assessment-SHA256"):
            raise ValueError("assessment digest mismatch")
        state = feedback_state_from_dict(json.loads(data))
        proof = implementer_assessment_terminal_evidence(state)
        if proof["spec_id"] != match.group(1):
            raise ValueError("assessment spec identity mismatch")
        candidate = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--end-of-options",
                                    f"{state.candidate_branch}^{{commit}}"], capture_output=True, text=True)
        if candidate.returncode or candidate.stdout.strip() != state.candidate_revision:
            raise ValueError("original candidate branch is missing or changed")
        for item in state.blocked_attempt.partial_work:
            revision = state.candidate_revision
            if item.change_kind == "deleted":
                present = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{revision}:{item.path}"],
                                         capture_output=True)
                if present.returncode == 0:
                    raise ValueError("deleted partial work path is still present")
                removed = subprocess.run(["git", "-C", str(repo), "--literal-pathspecs", "log", "-1",
                                          "--format=%H", "--diff-filter=D", revision, "--", item.path],
                                         capture_output=True, text=True)
                if removed.returncode or not removed.stdout.strip():
                    raise ValueError("deleted partial work has no retained origin")
                revision = removed.stdout.strip() + "^"
            blob = subprocess.run(["git", "-C", str(repo), "show", f"{revision}:{item.path}"], capture_output=True)
            if blob.returncode or hashlib.sha256(blob.stdout).hexdigest() != item.sha256:
                raise ValueError("partial work inventory does not match the retained candidate")
        return True, "validated implementer assessment; no verifier or delivery acceptance"
    except (ValueError, TypeError, KeyError, OSError) as error:
        return False, str(error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-staged", action="store_true")
    parser.add_argument("--check-assessment-resolution", type=Path, metavar="COMMIT_MESSAGE")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path(".nightshift/config.yaml"))
    parser.add_argument("--spec-id")
    parser.add_argument("--terminal", choices=("done", "blocked"))
    args = parser.parse_args(argv)
    if args.check_assessment_resolution:
        ok, detail = check_assessment_resolution(args.repo, args.check_assessment_resolution.read_text())
        if not ok:
            print(f"[nightshift terminal-outcomes] ERROR: {detail}", file=sys.stderr)
        return 0 if ok else 1
    config = load_config(args.config)
    if not configured(config):
        return 0
    if not args.check_staged or not args.spec_id or not args.terminal:
        parser.error("--check-staged, --spec-id, and --terminal are required")
    ok, detail = changed_matching_record(args.repo, args.spec_id, args.terminal, config)
    if not ok:
        print(f"[nightshift terminal-outcomes] ERROR: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
