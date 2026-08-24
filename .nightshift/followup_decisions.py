"""Durable, bounded recording for official follow-up decisions.

This is deliberately the narrow lifecycle seam retained by SPEC-236's
controller recovery.  It records a decision *after* the normal conflict/NFR
flow has determined its controlled outcome; it neither proposes work nor
creates a spec.  The operation key makes a replay of a terminal resolution
byte-idempotent.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml


SCHEMA_VERSION = 1
TERMINAL_RESOLUTIONS = frozenset({
    "done", "partial", "noop", "blocked", "unblock", "verifier_warning",
    "material_scope", "integration_failure", "post_release",
})
DECISION_OUTCOMES = frozenset({
    "created", "accepted_pending", "conflict_existing", "rejected_nfr",
    "rejected_not_needed", "tool_unavailable",
})
DISCOVERY_PHASES = frozenset({
    "implementation", "verification", "integration", "release", "post_release",
})


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "~")) or "://" in value:
        return False
    path = PurePosixPath(value)
    return ".." not in path.parts and not path.is_absolute()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _validate_record(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version", "operation_key", "run_id", "source_spec_id",
        "terminal_resolution", "discovery_phase", "suggestion_present",
        "outcome", "evidence_ref", "recorded_at",
    }
    for key in sorted(required - set(record)):
        errors.append(f"missing {key}")
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("operation_key", "run_id", "source_spec_id", "recorded_at"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            errors.append(f"{key} must be a non-empty string")
    if record.get("terminal_resolution") not in TERMINAL_RESOLUTIONS:
        errors.append("unknown terminal_resolution")
    if record.get("discovery_phase") not in DISCOVERY_PHASES:
        errors.append("unknown discovery_phase")
    if not isinstance(record.get("suggestion_present"), bool):
        errors.append("suggestion_present must be boolean")
    if record.get("outcome") not in DECISION_OUTCOMES:
        errors.append("unknown outcome")
    if not _safe_relative(record.get("evidence_ref")):
        errors.append("evidence_ref must be a safe relative path")
    if record.get("suggestion_present") is False and record.get("outcome") != "rejected_not_needed":
        errors.append("zero-suggestion observation must use rejected_not_needed")
    return errors


def _frontmatter(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("child spec has no frontmatter")
    end = text.find("\n---", 3)
    data = yaml.safe_load(text[3:end]) if end >= 0 else None
    if not isinstance(data, Mapping):
        raise ValueError("child spec frontmatter is invalid")
    return data


def seal_official_decision(
    root: Path, *, run_id: str, source_spec_id: str, terminal_resolution: str,
    discovery_phase: str, classification: Mapping[str, Any], evidence_ref: str,
    outcome: str, child_spec_id: str | None = None, specs_dir: Path | None = None,
    recorded_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Seal one official processor result with its source, classification and child state.

    The caller has already run conflict/NFR handling.  A ``created`` decision is
    accepted only after the actual child exists and carries the exact source
    backlink; all other outcomes must retain a null child.  This deliberately
    makes the lifecycle seam a verifier-visible boundary rather than a prose
    convention.
    """
    cause = classification.get("cause_class")
    detail = classification.get("detail_reason")
    planned = classification.get("planned_at_source_authoring")
    if not all(isinstance(value, str) and value for value in (cause, detail)) or not isinstance(planned, bool):
        raise ValueError("official decision requires controlled classification")
    if outcome == "created":
        if not child_spec_id or specs_dir is None:
            raise ValueError("created decision requires a resolved child spec")
        matches = list(Path(specs_dir).glob("*.md"))
        child_path = next((path for path in matches if _frontmatter(path).get("id") == child_spec_id), None)
        if child_path is None:
            raise ValueError("created child spec does not exist")
        followup = _frontmatter(child_path).get("followup")
        if not isinstance(followup, Mapping) or followup.get("source_spec_id") != source_spec_id or followup.get("outcome") != "created":
            raise ValueError("created child backlink is not sealed")
    elif child_spec_id is not None:
        raise ValueError("non-created decision may not carry a child")
    records, wrote = record_followup_decisions(
        root, run_id=run_id, source_spec_id=source_spec_id,
        terminal_resolution=terminal_resolution, discovery_phase=discovery_phase,
        evidence_ref=evidence_ref, outcomes=[outcome], contexts=[{
            "classification": {"cause_class": cause, "detail_reason": detail,
                               "planned_at_source_authoring": planned},
            "child_spec_id": child_spec_id,
        }], recorded_at=recorded_at,
    )
    return records[0], wrote


def record_followup_decisions(
    root: Path,
    *,
    run_id: str,
    source_spec_id: str,
    terminal_resolution: str,
    discovery_phase: str,
    evidence_ref: str,
    outcomes: Iterable[str],
    contexts: Iterable[Mapping[str, Any]] | None = None,
    recorded_at: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Persist exactly one controlled decision per suggestion, or one zero observation.

    ``outcomes`` is deliberately post-decision data: conflict checking and any
    NFR judgment remain the official callers' responsibility.  A same-key
    replay returns the existing bytes unchanged; a mismatched replay fails
    rather than silently rewriting lifecycle evidence.
    """
    values = list(outcomes)
    contexts_list = list(contexts or [])
    if not values:
        values = ["rejected_not_needed"]
        suggestion_flags = [False]
    else:
        suggestion_flags = [True] * len(values)
    if contexts_list and len(contexts_list) != len(values):
        raise ValueError("decision contexts must match outcomes")
    decisions: list[dict[str, Any]] = []
    wrote_any = False
    base = "\0".join((run_id, source_spec_id, terminal_resolution, discovery_phase, evidence_ref))
    for index, (outcome, suggestion_present) in enumerate(zip(values, suggestion_flags), start=1):
        operation_key = _sha(f"{base}\0{index}")
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "operation_key": operation_key,
            "run_id": run_id,
            "source_spec_id": source_spec_id,
            "terminal_resolution": terminal_resolution,
            "discovery_phase": discovery_phase,
            "suggestion_present": suggestion_present,
            "outcome": outcome,
            "evidence_ref": evidence_ref,
            "recorded_at": recorded_at or _now(),
        }
        if contexts_list:
            context = contexts_list[index - 1]
            record["classification"] = dict(context["classification"])
            record["child_spec_id"] = context.get("child_spec_id")
        errors = _validate_record(record)
        if errors:
            raise ValueError("; ".join(errors))
        path = Path(root) / "metrics" / "_wip" / "followup-decisions" / f"{operation_key}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            # Time is part of immutable evidence, so callers must pass it when
            # replaying across process boundaries.
            if existing != record:
                raise ValueError("operation key collision with different decision record")
        else:
            _atomic_json(path, record)
            wrote_any = True
        decisions.append(record)
    return decisions, wrote_any
