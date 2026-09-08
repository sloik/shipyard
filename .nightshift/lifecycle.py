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
    # SPEC-294 R3/Q4: a completed, verified candidate held pre-merge in an
    # `authorize` deployment environment awaiting a durable human
    # authorization record. Not `blocked` -- the wait is expected and
    # resolves the moment authorization is recorded.
    "awaiting_authorization",
})
BLOCKER_CLASSES = frozenset({
    "technical_infeasibility", "safety_constraint", "evidence_unavailable",
    "critical_external_constraint", "unknown_critical_failure",
    # SPEC-300-002 R2/R8: a failed evidence-gate check 6 (scope enforcement).
    # Not auto-eligible for the controller-backed unblock ladder -- a human
    # decides via a `## Scope Amendments` row on main, never an automatic
    # mechanism (unblock_spec.py special-cases this class; see SAFE_CLASSES).
    "scope_violation",
})
ATTEMPT_OUTCOMES_REQUIRING_ASSESSMENT = frozenset({
    "blocked", "failed", "refused", "stalled", "unavailable",
})
ORDINARY_EVIDENCE_WAIT_FAILURES = {
    "missing_browser_runtime": ("test_runtime", "browser_runtime"),
    "missing_api_runtime": ("api_runtime", "api_runtime"),
    "missing_test_runtime": ("test_runtime", "test_runtime"),
}
LIFECYCLE_TRANSITIONS = {
    "draft": frozenset({"planned", "ready", "blocked", "superseded"}),
    "planned": frozenset({"ready", "blocked", "superseded"}),
    "ready": frozenset({"planned", "in_progress", "blocked", "superseded"}),
    "in_progress": frozenset({"ready", "done", "blocked"}),
    "blocked": frozenset({"draft", "planned", "ready", "superseded"}),
}

# SPEC-291 R2: the closed, registered artifact-type vocabulary. Adding a type
# is a registry edit plus its documentation (SPEC-GUIDE.md), nowhere else.
ARTIFACT_TYPES = frozenset({
    "status-transition", "decision", "validation-evidence", "context",
    "verifier", "other",
})

# SPEC-291 R1: the single source for the artifact index schema. Prose in
# SPEC-GUIDE.md documents exactly this field list; a test proves they cannot
# drift (see tests/test_artifact_index_schema.py).
ARTIFACT_INDEX_FIELDS = ("type", "created", "actor", "summary", "path")

# SPEC-291 R3: the literal, closed set of (from, to) pairs whose reason may be
# synthesized from evidence already in hand (run ID / evidence trailers)
# rather than demanded as prose. Every other transition between two
# LIFECYCLE_STATUSES is a judgment transition and requires a non-empty
# prose reason.
MECHANICAL_TRANSITIONS = frozenset({
    ("ready", "in_progress"),
    ("in_progress", "done"),
    ("blocked", "ready"),
})


def terminal_statuses() -> frozenset[str]:
    """Return lifecycle statuses with no outgoing transition.

    ``LIFECYCLE_TRANSITIONS`` has no key for ``done`` or ``superseded``:
    ``transition_allowed`` falls back to ``LIFECYCLE_TRANSITIONS.get(current,
    ())``, which is empty for both, so both are structural dead ends. This
    derives that set from the registry itself rather than hardcoding it, so a
    future added/removed status stays in sync automatically.
    """
    return LIFECYCLE_STATUSES - frozenset(LIFECYCLE_TRANSITIONS.keys())


def attempt_requires_delivery_assessment(role: str, outcome: str) -> bool:
    """Keep an implementer terminal attempt distinct from parent delivery closure."""
    return role == "implementer" and outcome in ATTEMPT_OUTCOMES_REQUIRING_ASSESSMENT


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

    requirement_ids = set(re.findall(r"\bR(\d+)\s*(?:\([^)\n]*\))?\s*(?::|\.)", body))
    ac_ids = set(re.findall(r"\bAC(\d+)\s*(?:\([^)\n]*\))?\s*:", body))
    ac_reference_ids = {
        reference_id
        for parenthetical in re.findall(r"\bAC\d+\s*\(([^)\n]*)\)\s*:", body)
        for reference_id in re.findall(r"\bR(\d+)\b", parenthetical)
    }
    traceability_errors: list[str] = []
    if not requirement_ids or not ac_ids:
        traceability_errors.append("requirements and acceptance criteria need stable IDs")
    elif missing_reference_ids := sorted(ac_reference_ids - requirement_ids, key=int):
        traceability_errors.append(
            "acceptance criteria reference missing requirement IDs: "
            + ", ".join(f"R{reference_id}" for reference_id in missing_reference_ids)
        )
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
    frontmatter: Mapping[str, Any],
    body: str,
    specs: Mapping[str, Mapping[str, Any]] | None = None,
    dependency_errors: Mapping[str, str] | None = None,
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
    resolution_failures = [
        dependency_errors[dep]
        for dep in frontmatter.get("after", [])
        if dependency_errors and dep in dependency_errors
    ]
    if resolution_failures:
        return AdmissionResult("validation_failed", "; ".join(resolution_failures), readiness)
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


def classify_ordinary_evidence_wait(error_type: str) -> dict[str, str] | None:
    """Classify declared expected evidence-runtime absences without parsing logs.

    The vocabulary deliberately contains capability classes rather than command
    output, paths, hosts, or credentials.  Callers must use one of these
    explicit error types; all other failures retain the critical-block route.
    """
    classified = ORDINARY_EVIDENCE_WAIT_FAILURES.get(error_type)
    if classified is None:
        return None
    category, missing_capability = classified
    return {
        "category": category,
        "missing_capability": missing_capability,
        "resolution_state": "awaiting_capability",
        "next_action": f"provide {missing_capability} and rerun the evidence gate",
    }


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


def is_judgment_transition(current: str, target: str) -> bool:
    """Return whether a transition requires a prose reason (SPEC-291 R3).

    Scoped to the seven ``LIFECYCLE_STATUSES``: a transition touching a
    status outside that set (NFR-family ``active``/``retired``, for example)
    is outside this spec's enumerated vocabulary and is never required to
    carry a reason here. Within that set, every pair except the closed
    ``MECHANICAL_TRANSITIONS`` list is a judgment transition.
    """
    if current not in LIFECYCLE_STATUSES or target not in LIFECYCLE_STATUSES:
        return False
    return (current, target) not in MECHANICAL_TRANSITIONS


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
