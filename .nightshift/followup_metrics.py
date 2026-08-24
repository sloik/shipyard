"""Immutable, privacy-safe lineage records for Nightshift follow-up work.

The module is deliberately independent of a board, model, or harness.  A caller
records the evidence-backed decision it made; this module validates, seals and
aggregates that evidence without interpreting report prose or spec ID shape.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

SCHEMA_VERSION = 1
CAUSE_DETAILS = {
    "source_contract_gap": {"requirement_omission", "acceptance_criterion_omission", "scope_boundary_error", "dependency_or_integration_omission", "test_or_oracle_omission", "release_or_delivery_omission", "portability_or_environment_omission"},
    "planned_decomposition": {"declared_next_in_chain", "declared_out_of_scope", "activation_gate"},
    "implementation_defect": {"implementation_did_not_meet_contract", "regression_in_landed_work", "tooling_defect"},
    "external_change": {"dependency_changed", "platform_changed", "user_requirement_changed", "new_policy_or_nfr"},
    "evidence_only_completion": {"live_validation", "independent_verification", "release_evidence", "benchmark_or_calibration"},
    "measured_optimization": {"performance_opportunity", "cost_opportunity", "usability_opportunity", "reliability_opportunity"},
    "legacy_unclassified": {"insufficient_structured_evidence", "conflicting_evidence"},
}
DISCOVERY_PHASES = frozenset({"authoring", "implementation", "verification", "integration", "live_validation", "release", "post_release", "manual_review"})
OUTCOMES = frozenset({"created", "accepted_pending", "conflict_existing", "rejected_nfr", "rejected_not_needed", "tool_unavailable"})
TERMINAL_OUTCOMES = frozenset({"done", "partial", "noop", "blocked", "unblock", "verifier_warning", "material_scope", "integration_failure", "post_release"})
PUBLIC_ALLOWED = frozenset({"schema_version", "window", "rates", "distributions", "summary", "coverage", "suppressed_cohort_count", "source_hashes"})
MAX_RECORD_BYTES = 65_536
MAX_EVIDENCE_REFS = 32


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "~")) or "://" in value:
        return False
    path = PurePosixPath(value)
    return ".." not in path.parts and not path.is_absolute()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _spec_frontmatter(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"spec has no frontmatter: {path}")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError(f"spec has no closing frontmatter: {path}")
    parsed = yaml.safe_load(text[3:end]) or {}
    if not isinstance(parsed, Mapping) or not isinstance(parsed.get("id"), str):
        raise ValueError(f"spec has no id: {path}")
    return parsed


def derive_source_contract_incomplete(cause_class: str) -> bool | None:
    if cause_class == "source_contract_gap":
        return True
    if cause_class == "legacy_unclassified":
        return None
    if cause_class in CAUSE_DETAILS:
        return False
    raise ValueError(f"unknown cause_class: {cause_class}")


def validate_lineage_record(record: Mapping[str, Any], *, specs_dir: Path | None = None) -> list[str]:
    """Return deterministic validation errors; never infer missing lineage."""
    errors: list[str] = []
    required = ("schema_version", "operation_key", "project_id", "run_id", "source_spec_id", "child_spec_id", "discovery_phase", "cause_class", "detail_reason", "planned_at_source_authoring", "outcome", "evidence_refs", "source_hash", "created_at")
    for key in required:
        if key not in record:
            errors.append(f"missing {key}")
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    cause = record.get("cause_class")
    detail = record.get("detail_reason")
    if cause not in CAUSE_DETAILS:
        errors.append("unknown cause_class")
    elif detail not in CAUSE_DETAILS[cause]:
        errors.append("detail_reason is not allowed for cause_class")
    if record.get("discovery_phase") not in DISCOVERY_PHASES:
        errors.append("unknown discovery_phase")
    if record.get("outcome") not in OUTCOMES:
        errors.append("unknown outcome")
    planned = record.get("planned_at_source_authoring")
    if not isinstance(planned, bool):
        errors.append("planned_at_source_authoring must be boolean")
    elif cause == "planned_decomposition" and not planned:
        errors.append("planned_decomposition requires planned_at_source_authoring true")
    elif cause != "planned_decomposition" and planned:
        errors.append("only planned_decomposition may be planned_at_source_authoring")
    expected = derive_source_contract_incomplete(cause) if cause in CAUSE_DETAILS else None
    if "source_contract_incomplete" in record and record["source_contract_incomplete"] != expected:
        errors.append("source_contract_incomplete disagrees with derived cause class")
    child = record.get("child_spec_id")
    if child is not None and (not isinstance(child, str) or not child.strip()):
        errors.append("child_spec_id must be a non-empty string or null")
    if record.get("outcome") == "created" and child is None:
        errors.append("created outcome requires child_spec_id")
    if record.get("outcome") != "created" and child is not None:
        errors.append("only created outcome may carry child_spec_id")
    refs = record.get("evidence_refs")
    if not isinstance(refs, list) or not refs or len(refs) > MAX_EVIDENCE_REFS or any(not _safe_reference(ref) for ref in refs):
        errors.append("evidence_refs must be non-empty safe relative paths")
    for key in ("operation_key", "project_id", "run_id", "source_spec_id", "source_hash", "created_at"):
        if not isinstance(record.get(key), str) or not str(record[key]).strip():
            errors.append(f"{key} must be a non-empty string")
    source_hash = record.get("source_hash")
    if isinstance(source_hash, str) and (len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash.lower())):
        errors.append("source_hash must be a SHA-256 hex digest")
    if specs_dir is not None:
        ids = {str(_spec_frontmatter(path)["id"]) for path in specs_dir.glob("*.md") if not path.name.startswith("_")}
        if record.get("source_spec_id") not in ids:
            errors.append("source_spec_id does not resolve")
        if child is not None and child not in ids:
            errors.append("child_spec_id does not resolve")
        if child == record.get("source_spec_id"):
            errors.append("child_spec_id may not self-reference source")
    return errors


def build_record(*, project_id: str, run_id: str, source_spec_id: str, child_spec_id: str | None,
                 discovery_phase: str, cause_class: str, detail_reason: str,
                 planned_at_source_authoring: bool, outcome: str, evidence_refs: list[str],
                 source_hash: str, operation_key: str | None = None, created_at: str | None = None) -> dict[str, Any]:
    """Build a complete record and fail before it can be persisted if invalid."""
    record = {"schema_version": SCHEMA_VERSION, "operation_key": operation_key or _sha("\0".join([project_id, run_id, source_spec_id, child_spec_id or "", discovery_phase, cause_class, detail_reason, outcome])), "project_id": project_id, "run_id": run_id, "source_spec_id": source_spec_id, "child_spec_id": child_spec_id, "discovery_phase": discovery_phase, "cause_class": cause_class, "detail_reason": detail_reason, "planned_at_source_authoring": planned_at_source_authoring, "source_contract_incomplete": derive_source_contract_incomplete(cause_class), "outcome": outcome, "evidence_refs": sorted(set(evidence_refs)), "source_hash": source_hash, "created_at": created_at or _utc_now()}
    errors = validate_lineage_record(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
        handle.write(encoded)
        handle.flush(); os.fsync(handle.fileno())
        temp = Path(handle.name)
    os.replace(temp, path)


def append_record(store_path: Path, record: Mapping[str, Any], *, specs_dir: Path | None = None) -> tuple[dict[str, Any], bool]:
    """Append once by stable operation key. Identical retries are byte-idempotent."""
    if len(json.dumps(record, sort_keys=True).encode()) > MAX_RECORD_BYTES:
        raise ValueError("lineage record exceeds bounded size")
    errors = validate_lineage_record(record, specs_dir=specs_dir)
    if errors:
        raise ValueError("; ".join(errors))
    if store_path.exists() and store_path.is_symlink():
        raise ValueError("lineage store may not be a symlink")
    # Advisory file locking prevents concurrent writers from losing a decision.
    lock_path = store_path.with_suffix(store_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    import fcntl
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = json.loads(store_path.read_text()) if store_path.exists() else []
        if not isinstance(existing, list):
            raise ValueError("lineage store must be a JSON array")
        for prior in existing:
            if prior.get("operation_key") == record["operation_key"]:
                if prior != dict(record):
                    raise ValueError("operation key collision with different record")
                return prior, False
        existing.append(dict(record)); existing.sort(key=lambda item: item["operation_key"])
        _atomic_json(store_path, existing)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return dict(record), True


def process_decision(*, store_path: Path, specs_dir: Path, record: Mapping[str, Any],
                     child_path: Path | None = None, child_markdown: str | None = None) -> tuple[dict[str, Any], bool]:
    """Seal a decision, creating a validated child before a `created` outcome.

    This is the official integration boundary for normal, noop, partial,
    blocked/unblock, verifier, integration and post-release callers: each passes
    its discovery phase and outcome rather than encoding a special flow here.
    """
    data = dict(record)
    if data.get("outcome") == "created":
        if child_path is None or child_markdown is None:
            raise ValueError("created decision requires child_path and child_markdown")
        if child_path.exists():
            existing = _spec_frontmatter(child_path)
            if existing.get("id") != data.get("child_spec_id"):
                raise ValueError("existing child ID disagrees with decision")
        else:
            child_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = child_path.with_suffix(child_path.suffix + ".tmp")
            tmp.write_text(child_markdown, encoding="utf-8")
            os.replace(tmp, child_path)
        child = _spec_frontmatter(child_path)
        backlink = child.get("followup")
        if not isinstance(backlink, Mapping) or backlink.get("source_spec_id") != data.get("source_spec_id") or backlink.get("outcome") != "created":
            raise ValueError("child backlink disagrees with lineage decision")
        if child.get("id") != data.get("child_spec_id"):
            raise ValueError("child ID disagrees with lineage decision")
    return append_record(store_path, data, specs_dir=specs_dir)


def zero_suggestion_record(*, project_id: str, run_id: str, source_spec_id: str, source_hash: str,
                           terminal_outcome: str, evidence_ref: str, created_at: str | None = None) -> dict[str, Any]:
    if terminal_outcome not in TERMINAL_OUTCOMES:
        raise ValueError("unknown terminal outcome")
    return build_record(project_id=project_id, run_id=run_id, source_spec_id=source_spec_id,
        child_spec_id=None, discovery_phase="verification", cause_class="legacy_unclassified",
        detail_reason="insufficient_structured_evidence", planned_at_source_authoring=False,
        outcome="rejected_not_needed", evidence_refs=[evidence_ref], source_hash=source_hash,
        operation_key=_sha(f"zero\0{project_id}\0{run_id}\0{source_spec_id}\0{terminal_outcome}"), created_at=created_at)


def _rate(numerator: int, denominator: int) -> dict[str, int | float | str | None]:
    return {"numerator": numerator, "eligible_denominator": denominator, "value": None if not denominator else numerator / denominator, "sample_state": "no_samples" if not denominator else "sampled"}


def aggregate(records: Iterable[Mapping[str, Any]], *, window: Mapping[str, str] | None = None, minimum_cohort_size: int = 2) -> dict[str, Any]:
    """Aggregate only sealed explicit records, deduplicating stable operations."""
    unique = {str(r.get("operation_key")): dict(r) for r in records}
    rows = list(unique.values())
    for row in rows:
        errors = validate_lineage_record(row)
        if errors: raise ValueError("invalid lineage input: " + "; ".join(errors))
    eligible = {r["source_spec_id"] for r in rows}
    created_or_pending = [r for r in rows if r["outcome"] in {"created", "accepted_pending"}]
    def sources(predicate: Any) -> set[str]: return {r["source_spec_id"] for r in created_or_pending if predicate(r)}
    denominator = len(eligible)
    any_sources = sources(lambda r: True)
    gaps = sources(lambda r: r["cause_class"] == "source_contract_gap")
    planned = sources(lambda r: r["cause_class"] == "planned_decomposition")
    late = sources(lambda r: r["cause_class"] == "source_contract_gap" and r["discovery_phase"] in {"integration", "live_validation", "release", "post_release"})
    accepted_keys = {r["operation_key"] for r in created_or_pending}
    created_keys = {r["operation_key"] for r in rows if r["outcome"] == "created"}
    child_ids = {r["child_spec_id"] for r in rows if r["outcome"] == "created" and r["child_spec_id"]}
    children_per_source = [sum(1 for r in rows if r["outcome"] == "created" and r["source_spec_id"] == source) for source in sorted(eligible)]
    def distribution(key: str) -> dict[str, int]: return dict(sorted(Counter(str(r[key]) for r in rows).items()))
    ordered_children = sorted(children_per_source)
    summary = {"count": len(children_per_source), "min": min(children_per_source, default=0), "median": statistics.median(children_per_source) if children_per_source else None, "p90": ordered_children[max(0, int(__import__('math').ceil(len(ordered_children) * .9) - 1))] if children_per_source else None, "max": max(children_per_source, default=0), "mean": (sum(children_per_source)/len(children_per_source)) if children_per_source else None}
    cohorts: dict[str, dict[str, int | str]] = {}
    for row in rows:
        characteristics = row.get("source_characteristics") if isinstance(row.get("source_characteristics"), Mapping) else {}
        for key in ("type", "domain", "layer", "template_version", "requirement_count_bucket", "ac_count_bucket", "touches_count_bucket", "nfr_count_bucket", "prior_attempt_presence", "contract_friction", "review_cycle_bucket", "terminal_outcome"):
            value = str(characteristics.get(key, "unknown"))
            bucket = cohorts.setdefault(f"{key}:{value}", {"eligible": 0, "with_followup": 0})
            bucket["eligible"] = int(bucket["eligible"]) + 1
            if row["outcome"] in {"created", "accepted_pending"}: bucket["with_followup"] = int(bucket["with_followup"]) + 1
    suppressed = sum(1 for value in cohorts.values() if int(value["eligible"]) < minimum_cohort_size)
    public_cohorts = {key: value for key, value in cohorts.items() if int(value["eligible"]) >= minimum_cohort_size}
    return {"schema_version": SCHEMA_VERSION, "window": dict(window or {}), "rates": {"any_followup_required_rate": _rate(len(any_sources), denominator), "unplanned_contract_gap_source_rate": _rate(len(gaps), denominator), "planned_followup_source_rate": _rate(len(planned), denominator), "late_contract_gap_source_rate": _rate(len(late), denominator), "followup_creation_conversion_rate": _rate(len(created_keys), len(accepted_keys)), "lineage_coverage_rate": _rate(len(child_ids), len(child_ids)), "historical_classification_coverage_rate": _rate(sum(r["cause_class"] != "legacy_unclassified" for r in rows), len(rows))}, "summary": {"eligible_source_specs": denominator, "unique_child_specs": len(child_ids), "followup_children_per_eligible_source": summary}, "distributions": {"cause_class": distribution("cause_class"), "detail_reason": distribution("detail_reason"), "discovery_phase": distribution("discovery_phase"), "outcome": distribution("outcome")}, "cohorts": public_cohorts, "coverage": {"records": len(rows), "minimum_cohort_size": minimum_cohort_size}, "suppressed_cohort_count": suppressed, "source_hashes": sorted({r["source_hash"] for r in rows})}


def public_projection(aggregate_result: Mapping[str, Any]) -> dict[str, Any]:
    """Strip project-local identity/prose by an allowlist, not a blacklist."""
    return {key: aggregate_result[key] for key in PUBLIC_ALLOWED if key in aggregate_result}


def backfill(explicit_records: Iterable[Mapping[str, Any]], output_path: Path) -> dict[str, int]:
    """Read-only backfill: callers provide only explicit evidence-derived records."""
    records = list(explicit_records)
    conflicts = 0
    valid: list[Mapping[str, Any]] = []
    seen: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if validate_lineage_record(record):
            conflicts += 1; continue
        key = str(record["operation_key"])
        if key in seen and seen[key] != record:
            conflicts += 1; continue
        seen[key] = record; valid.append(record)
    _atomic_json(output_path, sorted(valid, key=lambda item: item["operation_key"]))
    return {"scanned": len(records), "eligible": len(valid), "classified": sum(r["cause_class"] != "legacy_unclassified" for r in valid), "conflicting": conflicts, "skipped": len(records) - len(valid)}


def backfill_from_explicit_artifacts(paths: Iterable[Path], output_path: Path) -> dict[str, int]:
    """Import only JSON objects that already declare a complete lineage record.

    Markdown prose, `after:` relationships and names are deliberately never read
    as evidence. Conflicting operation keys are preserved as quarantine rows.
    """
    records: list[Mapping[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for path in sorted(paths, key=lambda item: str(item)):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, Mapping) and "operation_key" in item:
                records.append(item)
    summary = backfill(records, output_path)
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in records:
        key = str(item.get("operation_key"))
        grouped[key].append(item)
    for key, rows in sorted(grouped.items()):
        distinct = {json.dumps(row, sort_keys=True) for row in rows}
        if len(distinct) > 1:
            quarantine.append({"operation_key": key, "reason_code": "conflicting_explicit_evidence",
                "source_hashes": sorted({str(row.get("source_hash", "")) for row in rows}),
                "evidence_hashes": sorted(_sha(json.dumps(row, sort_keys=True)) for row in rows)})
    _atomic_json(output_path.with_name(output_path.stem + "-conflicts.json"), quarantine)
    return summary
