"""Deterministic lifecycle, readiness, and run-admission rules.

Stored ``status`` answers where a spec is in its lifecycle.  This module never
uses a closed admission gate to mutate that status; callers can therefore show
why an otherwise ready spec is not runnable without misclassifying it blocked.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Readiness(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class ScopeRevision(StrEnum):
    MINOR = "minor"
    MATERIAL = "material"


class GapDisposition(StrEnum):
    FOLLOW_UP = "non_blocking_follow_up"
    PREREQUISITE = "actionable_prerequisite"
    CONTRACT_REVISION = "contract_ambiguity_or_redesign"
    CRITICAL_BLOCKER = "critical_constraint"


LIFECYCLE_STATUSES = frozenset({
    "draft", "planned", "ready", "in_progress", "blocked", "done", "superseded",
})
RUN_STATES = frozenset({
    "runnable", "specification_incomplete", "intentionally_future",
    "validation_failed", "review_required", "waiting_dependencies",
    "waiting_external_input", "time_gated", "overlap_conflict",
    "dependency_cycle", "resource_gated", "waiting_gap_spec",
})
BLOCKER_CLASSES = frozenset({
    "technical_infeasibility", "safety_constraint", "evidence_unavailable",
    "critical_external_constraint", "unknown_critical_failure",
})
LIFECYCLE_TRANSITIONS = {
    "draft": frozenset({"planned", "ready", "blocked", "superseded"}),
    "planned": frozenset({"ready", "blocked", "superseded"}),
    "ready": frozenset({"planned", "in_progress", "blocked", "superseded"}),
    "in_progress": frozenset({"ready", "done", "blocked"}),
    "blocked": frozenset({"draft", "planned", "ready", "superseded"}),
}
ORDINARY_BLOCKER_PATTERNS = (
    "waiting for spec-", "waiting on spec-", "missing work", "planned scheduling",
    "intentionally future", "time gated", "temporary external", "awaiting external",
)


@dataclass(frozen=True)
class ReadinessDimension:
    name: str
    level: Readiness
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadinessResult:
    level: Readiness
    findings: tuple[str, ...] = ()
    dimensions: tuple[ReadinessDimension, ...] = ()


@dataclass(frozen=True)
class AdmissionResult:
    state: str
    reason: str
    readiness: ReadinessResult


@dataclass(frozen=True)
class ScopeExtractionResult:
    level: Readiness
    outcome: str
    status: str
    findings: tuple[str, ...] = ()
    scope_split: bool = False


def intrinsic_readiness(frontmatter: Mapping[str, Any], body: str) -> ReadinessResult:
    """Return the deterministic per-dimension intrinsic readiness gate."""
    dimensions: list[ReadinessDimension] = []

    schema_errors = [
        message for present, message in (
            (str(frontmatter.get("id", "")).strip(), "missing spec id"),
            (str(frontmatter.get("status", "")).strip(), "missing lifecycle status"),
        ) if not present
    ]
    dimensions.append(ReadinessDimension(
        "schema", Readiness.FAIL if schema_errors else Readiness.PASS, tuple(schema_errors)
    ))

    section_errors = [
        f"missing {section[3:].lower()} section"
        for section in ("## Requirements", "## Acceptance Criteria")
        if section not in body
    ]
    dimensions.append(ReadinessDimension(
        "sections", Readiness.FAIL if section_errors else Readiness.PASS, tuple(section_errors)
    ))

    nfr_errors: list[str] = []
    if (
        frontmatter.get("type") in {"feature", "bugfix", "refactor"}
        and ("nfrs" not in frontmatter or not isinstance(frontmatter.get("nfrs"), list))
    ):
        nfr_errors.append("feature/bugfix/refactor requires an explicit nfrs list")
    dimensions.append(ReadinessDimension(
        "nfr_reconciliation", Readiness.FAIL if nfr_errors else Readiness.PASS, tuple(nfr_errors)
    ))

    after = frontmatter.get("after", [])
    dependency_errors = (
        ["after must be a list of non-empty spec IDs"]
        if not isinstance(after, list) or any(not str(dep).strip() for dep in after)
        else []
    )
    dimensions.append(ReadinessDimension(
        "dependency_references",
        Readiness.FAIL if dependency_errors else Readiness.PASS,
        tuple(dependency_errors),
    ))

    unresolved = (
        ["unresolved marker"]
        if "TODO" in body or "TBD" in body or "[question]" in body.lower()
        else []
    )
    dimensions.append(ReadinessDimension(
        "unresolved_markers", Readiness.REVIEW if unresolved else Readiness.PASS, tuple(unresolved)
    ))

    requirement_ids = set(re.findall(r"\bR(\d+)\s*:", body))
    ac_ids = set(re.findall(r"\bAC(\d+)\s*:", body))
    traceability_errors: list[str] = []
    if not requirement_ids or not ac_ids:
        traceability_errors.append("requirements and acceptance criteria need stable IDs")
    elif requirement_ids != ac_ids:
        traceability_errors.append("requirement/acceptance-criterion IDs are not traceable one-to-one")
    dimensions.append(ReadinessDimension(
        "requirement_ac_traceability",
        Readiness.FAIL if traceability_errors else Readiness.PASS,
        tuple(traceability_errors),
    ))

    findings = tuple(evidence for dimension in dimensions for evidence in dimension.evidence)
    if any(dimension.level is Readiness.FAIL for dimension in dimensions):
        level = Readiness.FAIL
    elif any(dimension.level is Readiness.REVIEW for dimension in dimensions):
        level = Readiness.REVIEW
    else:
        level = Readiness.PASS
    return ReadinessResult(level, findings, tuple(dimensions))


def derive_admission(
    frontmatter: Mapping[str, Any], body: str, specs: Mapping[str, Mapping[str, Any]] | None = None,
) -> AdmissionResult:
    """Derive an observable run state without changing ``frontmatter['status']``."""
    readiness = intrinsic_readiness(frontmatter, body)
    status = str(frontmatter.get("status", ""))
    if status == "draft":
        return AdmissionResult("specification_incomplete", "draft specification", readiness)
    if status == "planned":
        return AdmissionResult("intentionally_future", "explicitly planned for later", readiness)
    if readiness.level is Readiness.FAIL:
        return AdmissionResult("validation_failed", "; ".join(readiness.findings), readiness)
    if readiness.level is Readiness.REVIEW:
        return AdmissionResult("review_required", "; ".join(readiness.findings), readiness)
    for key, state in (("external_input", "waiting_external_input"), ("not_before", "time_gated"),
                       ("resource_gate", "resource_gated"), ("overlap_conflict", "overlap_conflict"),
                       ("gap_spec", "waiting_gap_spec")):
        if frontmatter.get(key):
            return AdmissionResult(state, f"declared {key}", readiness)
    if specs is not None:
        unmet = [dep for dep in frontmatter.get("after", [])
                 if dep not in specs or specs[dep].get("status") != "done"]
        if unmet:
            return AdmissionResult("waiting_dependencies", f"unfinished dependencies: {', '.join(unmet)}", readiness)
    return AdmissionResult("runnable", "all deterministic admission gates passed", readiness)


def validate_blocked(frontmatter: Mapping[str, Any]) -> list[str]:
    """Return errors for a blocked spec lacking exceptional, evidenced grounds."""
    if frontmatter.get("status") != "blocked":
        return []
    errors: list[str] = []
    for key in ("blocker_class", "block_reason", "blocked_since", "unblock_condition", "blocker_scope", "blocker_evidence"):
        if not str(frontmatter.get(key, "")).strip():
            errors.append(f"blocked status requires {key}")
    if str(frontmatter.get("blocker_class", "")) not in BLOCKER_CLASSES:
        errors.append("blocked status requires a documented critical blocker_class")
    reason = str(frontmatter.get("block_reason", "")).lower()
    if any(pattern in reason for pattern in ORDINARY_BLOCKER_PATTERNS):
        errors.append("blocked reason describes an ordinary admission wait, not a critical constraint")
    return errors


def migrate_legacy_planning(frontmatter: Mapping[str, Any]) -> tuple[str | None, ReadinessResult]:
    """Classify legacy planning deterministically; ambiguity is REVIEW, not guessed."""
    if frontmatter.get("status") != "planning":
        return None, ReadinessResult(Readiness.PASS)
    if frontmatter.get("legacy_planning_intent") == "future":
        return "planned", ReadinessResult(Readiness.PASS)
    if frontmatter.get("type") == "main" or frontmatter.get("legacy_planning_intent") == "decomposition":
        return "draft", ReadinessResult(Readiness.PASS)
    return None, ReadinessResult(Readiness.REVIEW, ("legacy planning intent is ambiguous",))


def transition_allowed(current: str, target: str) -> bool:
    return target in LIFECYCLE_TRANSITIONS.get(current, ())


def validate_scope_extraction(
    removed: Iterable[str], mappings: Mapping[str, str], *, backlinks: Iterable[str],
    retained_ac_pass: bool, coordinator_approved: bool, executor_id: str, coordinator_id: str,
) -> ScopeExtractionResult:
    """Validate atomic scope extraction before any contract text is removed."""
    removed = tuple(removed)
    missing = [item for item in removed if not mappings.get(item)]
    findings: list[str] = []
    if missing:
        findings.append("missing destination mapping: " + ", ".join(missing))
    if set(mappings.values()) - set(backlinks):
        findings.append("destination spec lacks provenance backlink")
    if not retained_ac_pass:
        findings.append("retained acceptance criteria are not verified")
    if not coordinator_approved or executor_id == coordinator_id:
        findings.append("independent coordinator approval is required")
    if findings:
        return ScopeExtractionResult(Readiness.FAIL, "partial", "ready", tuple(findings))
    return ScopeExtractionResult(Readiness.PASS, "done", "done", scope_split=True)


def classify_scope_revision(
    *, user_visible_behavior: bool = False, acceptance_intent: bool = False,
    invalidates_evidence: bool = False, architectural_layer: bool = False,
    hard_dependency: bool = False,
) -> ScopeRevision:
    """Apply R8's deterministic material-change threshold."""
    return (
        ScopeRevision.MATERIAL
        if any((
            user_visible_behavior, acceptance_intent, invalidates_evidence,
            architectural_layer, hard_dependency,
        ))
        else ScopeRevision.MINOR
    )


def classify_gap(disposition: GapDisposition) -> dict[str, Any]:
    """Return the lifecycle/run-state action for each R6 gap disposition."""
    actions = {
        GapDisposition.FOLLOW_UP: {
            "create_gap_spec": True, "status": "in_progress", "run_state": "runnable",
        },
        GapDisposition.PREREQUISITE: {
            "create_gap_spec": True, "status": "ready", "run_state": "waiting_gap_spec",
        },
        GapDisposition.CONTRACT_REVISION: {
            "create_gap_spec": False, "status": "draft", "run_state": "specification_incomplete",
        },
        GapDisposition.CRITICAL_BLOCKER: {
            "create_gap_spec": False, "status": "blocked", "run_state": "review_required",
        },
    }
    return dict(actions[disposition])


def scope_outcome_record(
    extraction: ScopeExtractionResult, *, retained_ac_pass: bool,
    prior_outcomes: Iterable[Mapping[str, Any]], evidence: Iterable[str],
) -> dict[str, Any]:
    """Resolve retained scope while copying historical outcomes/evidence immutably."""
    history = deepcopy(list(prior_outcomes))
    retained_evidence = tuple(evidence)
    complete = extraction.level is Readiness.PASS and retained_ac_pass
    return {
        "outcome": "done" if complete else "partial",
        "status": "done" if complete else "ready",
        "scope_split": bool(complete and extraction.scope_split),
        "retained_evidence": retained_evidence,
        "prior_outcomes": history,
    }


def decision_record(*, trigger: str, current_state: str, candidates: Iterable[str], reason: str,
                    findings: Iterable[str], resolution: str | None = None,
                    rationale: str | None = None, authority: str | None = None) -> dict[str, Any]:
    """Produce the immutable-shaped record required for an ambiguous classification."""
    return {"trigger": trigger, "current_state": current_state, "candidate_states": list(candidates),
            "ambiguity_reason": reason, "static_findings": list(findings),
            "resolution": resolution, "rationale": rationale, "decision_authority": authority,
            "reusable_rule_gap": resolution is None}


def resolve_decision_record(
    original: Mapping[str, Any], *, resolution: str, rationale: str,
    authority: str, reusable_rule_gap: bool,
) -> dict[str, Any]:
    """Resolve a REVIEW record without deleting its original ambiguity evidence."""
    resolved = deepcopy(dict(original))
    resolved["original_ambiguity"] = {
        key: deepcopy(original.get(key))
        for key in (
            "trigger", "current_state", "candidate_states", "ambiguity_reason",
            "static_findings",
        )
    }
    resolved.update({
        "resolution": resolution,
        "rationale": rationale,
        "decision_authority": authority,
        "reusable_rule_gap": reusable_rule_gap,
    })
    return resolved
