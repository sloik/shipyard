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
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

import yaml


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
# SPEC-359 R2: the declared-hold precedence, hoisted out of ``derive_admission``
# so the explanation's gate walk and the producer read one ordered literal and
# cannot drift. Order is the precedence; the first truthy key decides.
DECLARED_HOLD_GATES = (
    ("external_input", "waiting_external_input"), ("not_before", "time_gated"),
    ("resource_gate", "resource_gated"), ("overlap_conflict", "overlap_conflict"),
    ("gap_spec", "waiting_gap_spec"),
)
BLOCKER_CLASSES = frozenset({
    "technical_infeasibility", "safety_constraint", "evidence_unavailable",
    "critical_external_constraint", "unknown_critical_failure",
    # SPEC-300-002 R2/R8: a failed evidence-gate check 6 (scope enforcement).
    # Not auto-eligible for the controller-backed unblock ladder -- a human
    # decides via a `## Scope Amendments` row on main, never an automatic
    # mechanism (unblock_spec.py special-cases this class; see SAFE_CLASSES).
    "scope_violation",
})
# SPEC-350 R2: blocker classes with no automated recovery path at all -- not
# in `unblock_spec.SAFE_CLASSES` (never auto-retried) and not folded into
# `unblock_spec.SKIP_CLASSES` either, since a permanent, silent skip is
# exactly the stuck-forever failure mode this spec fixes. A human must review
# the pinned blocker evidence and record an explicit decision (see
# `unblock_spec.triage`). Single source of truth so `unblock_spec.py` and any
# future renderer agree on membership.
MANUAL_TRIAGE_CLASSES = frozenset({"unknown_critical_failure"})
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
    for key, state in DECLARED_HOLD_GATES:
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


def apply_authorization_overlay(
    admission: AdmissionResult, hold: Mapping[str, Any] | None,
) -> AdmissionResult:
    """SPEC-294 R3 overlay: a held candidate displays ``awaiting_authorization``.

    The board's existing rule, as one function the board and the SPEC-359 CLI
    explanation both call. The caller decides *whether* to look for a hold
    (only ``in_progress`` specs); this only applies a result already read.
    """
    if hold and hold.get("held"):
        return AdmissionResult(
            "awaiting_authorization",
            str(hold.get("reason") or "awaiting deployment authorization"),
            admission.readiness,
        )
    return admission


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


class StateRationaleError(ValueError):
    """Raised when a spec's ``## State rationale`` section is malformed."""


# SPEC-357 R1: the single source for the declaration schema. A version bump
# is a registry edit here plus SPEC-GUIDE.md/the templates, nowhere else.
STATE_RATIONALE_SCHEMA_VERSION = 1
STATE_RATIONALE_HEADING = "## State rationale"
STATE_RATIONALE_TEMPLATE_VERSION = 12
STATE_RATIONALE_FIELDS = (
    "schema_version", "status", "reason", "reconsider_when", "evidence",
    "provenance", "record",
)
# Compared for snapshot equality (R2); `record` is the self-reference and is
# excluded, matching "excludes the self-reference `record`" in the spec.
STATE_RATIONALE_SNAPSHOT_FIELDS = tuple(
    field for field in STATE_RATIONALE_FIELDS if field != "record"
)
STATE_RATIONALE_PROVENANCES = frozenset({"authored", "reconstructed"})
# R1: families with no required section/record; an optional section must
# still be well-formed if present.
STATE_RATIONALE_EXCLUDED_TYPES = frozenset({"main", "questions", "nfr"})
NONTERMINAL_LIFECYCLE_STATUSES_REQUIRING_TRIGGER = frozenset({"draft", "planned", "blocked"})

# R4: the closed evidence-locator vocabulary and its per-kind key shape.
STATE_RATIONALE_LOCATOR_SCHEMA: dict[str, dict[str, tuple[str, ...]]] = {
    "file": {"required": ("path",), "optional": ("anchor",)},
    "spec": {"required": ("id",), "optional": ("project", "anchor")},
    "artifact": {"required": ("spec", "path"), "optional": ("project",)},
    "git": {"required": ("commit", "path"), "optional": ("project",)},
    "url": {"required": ("url", "label"), "optional": ()},
}

_GIT_OBJECT_ID_RE = re.compile(r"\A[0-9a-f]{40}\Z|\A[0-9a-f]{64}\Z")
_STATE_RATIONALE_HEADING_RE = re.compile(
    r"^" + re.escape(STATE_RATIONALE_HEADING) + r"\s*$", re.MULTILINE
)
_FENCED_YAML_RE = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)
_NEXT_HEADING_RE = re.compile(r"^#{1,2} ", re.MULTILINE)


def requires_state_rationale(frontmatter: Mapping[str, Any]) -> bool:
    """R1: whether ``## State rationale`` is required for this spec.

    Excluded: ``type: main``/``questions``/``nfr`` and any ``NFR-`` ID. Every
    other lifecycle-status spec requires the section.
    """
    if frontmatter.get("type") in STATE_RATIONALE_EXCLUDED_TYPES:
        return False
    if str(frontmatter.get("id", "")).startswith("NFR-"):
        return False
    return True


def is_safe_relative_posix_path(value: Any) -> bool:
    """Forward-slash, non-absolute, no empty/``.``/``..`` path segment (R4)."""
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if PurePosixPath(value).is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def validate_state_rationale_locator(entry: Any) -> list[str]:
    """R4: validate one typed evidence locator against its closed kind schema."""
    if not isinstance(entry, Mapping):
        return ["evidence entry must be a mapping"]
    kind = entry.get("kind")
    schema = STATE_RATIONALE_LOCATOR_SCHEMA.get(kind)
    if schema is None:
        return [
            f"evidence kind {kind!r} is not on the registry: "
            f"{sorted(STATE_RATIONALE_LOCATOR_SCHEMA)}"
        ]
    allowed = {"kind", *schema["required"], *schema["optional"]}
    errors = [
        f"evidence[{kind}] has unknown key(s): {', '.join(sorted(set(entry) - allowed))}"
    ] if set(entry) - allowed else []
    errors += [
        f"evidence[{kind}] missing required key: {key}"
        for key in schema["required"] if not str(entry.get(key, "")).strip()
    ]
    if kind in {"file", "artifact", "git"} and entry.get("path") is not None \
            and not is_safe_relative_posix_path(entry.get("path")):
        errors.append(f"evidence[{kind}] path must be a safe relative path: {entry.get('path')!r}")
    if kind == "git" and entry.get("commit") is not None \
            and not _GIT_OBJECT_ID_RE.match(str(entry.get("commit"))):
        errors.append("evidence[git] commit must be a full 40- or 64-hex object id")
    if kind == "url":
        url = entry.get("url")
        if url is not None:
            if not str(url).lower().startswith("https://"):
                errors.append("evidence[url] must be an https:// URL")
            elif "@" in str(url)[len("https://"):].split("/", 1)[0]:
                errors.append("evidence[url] must not embed credentials")
    anchor = entry.get("anchor")
    if anchor is not None and (
        not isinstance(anchor, str) or not anchor.strip() or anchor.startswith("#")
    ):
        errors.append("evidence anchor must be a nonempty Markdown heading slug without '#'")
    return errors


def validate_state_rationale_mapping(mapping: Any) -> list[str]:
    """R1/R2/R4: validate one decoded ``## State rationale`` mapping."""
    if not isinstance(mapping, Mapping):
        return ["state rationale must be a YAML mapping"]
    errors: list[str] = []
    unknown = set(mapping) - set(STATE_RATIONALE_FIELDS)
    if unknown:
        errors.append(f"state rationale has unknown key(s): {', '.join(sorted(unknown))}")
    missing = [field for field in STATE_RATIONALE_FIELDS if field not in mapping]
    if missing:
        errors.append(f"state rationale missing required key(s): {', '.join(missing)}")
        return errors
    if mapping.get("schema_version") != STATE_RATIONALE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {STATE_RATIONALE_SCHEMA_VERSION}")
    for key in ("status", "reason", "provenance"):
        if not isinstance(mapping.get(key), str):
            errors.append(f"{key} must be a string")
    if isinstance(mapping.get("reason"), str) and not mapping["reason"].strip():
        errors.append("reason must be non-empty")
    if mapping.get("provenance") not in STATE_RATIONALE_PROVENANCES:
        errors.append(f"provenance must be one of {sorted(STATE_RATIONALE_PROVENANCES)}")
    reconsider_when = mapping.get("reconsider_when")
    if reconsider_when is not None and not isinstance(reconsider_when, str):
        errors.append("reconsider_when must be a string or null")
    status = mapping.get("status")
    if status in NONTERMINAL_LIFECYCLE_STATUSES_REQUIRING_TRIGGER \
            and not str(reconsider_when or "").strip():
        errors.append(
            "reconsider_when is required (non-empty) when status is draft/planned/blocked"
        )
    evidence = mapping.get("evidence")
    if not isinstance(evidence, list):
        errors.append("evidence must be a list")
    else:
        for index, entry in enumerate(evidence):
            errors += [f"evidence[{index}]: {error}" for error in validate_state_rationale_locator(entry)]
    record = mapping.get("record")
    if record is not None and (
        not isinstance(record, str) or not record.startswith("artifacts/")
        or not is_safe_relative_posix_path(record)
    ):
        errors.append("record must be null or 'artifacts/<relative-file>'")
    return errors


def state_rationale_snapshot(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """R2: the exact decoded mapping compared for equality, excluding ``record``."""
    return {field: deepcopy(mapping.get(field)) for field in STATE_RATIONALE_SNAPSHOT_FIELDS}


def state_rationale_snapshots_equal(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return state_rationale_snapshot(a) == state_rationale_snapshot(b)


def _state_rationale_section_span(body: str) -> tuple[int, int] | None:
    """Return the (start, end) character span of the section, or None if absent.

    Raises :class:`StateRationaleError` if more than one heading is present.
    """
    headings = list(_STATE_RATIONALE_HEADING_RE.finditer(body))
    if not headings:
        return None
    if len(headings) > 1:
        raise StateRationaleError("duplicate '## State rationale' sections")
    heading = headings[0]
    rest = body[heading.end():]
    next_heading = _NEXT_HEADING_RE.search(rest)
    end = heading.end() + (next_heading.start() if next_heading else len(rest))
    return heading.start(), end


def parse_state_rationale(body: str) -> dict[str, Any] | None:
    """Parse the body's ``## State rationale`` section (R1).

    Returns ``None`` when the section is absent. Ignores fenced YAML blocks
    that lie outside the section (e.g. worked examples in other headings).
    Raises :class:`StateRationaleError` for a duplicate section/mapping or
    invalid YAML.
    """
    span = _state_rationale_section_span(body)
    if span is None:
        return None
    start, end = span
    section_text = body[start:end]
    fences = list(_FENCED_YAML_RE.finditer(section_text))
    if not fences:
        raise StateRationaleError(f"{STATE_RATIONALE_HEADING} has no fenced YAML mapping")
    if len(fences) > 1:
        raise StateRationaleError(f"{STATE_RATIONALE_HEADING} has more than one fenced YAML mapping")
    try:
        mapping = yaml.safe_load(fences[0].group(1))
    except yaml.YAMLError as exc:
        raise StateRationaleError(f"{STATE_RATIONALE_HEADING} YAML is invalid: {exc}") from exc
    if not isinstance(mapping, dict):
        raise StateRationaleError(f"{STATE_RATIONALE_HEADING} must decode to a YAML mapping")
    return mapping


def render_state_rationale_section(mapping: Mapping[str, Any]) -> str:
    """Render the section text (heading + one fenced YAML mapping) for R1."""
    ordered = {field: mapping.get(field) for field in STATE_RATIONALE_FIELDS if field in mapping}
    yaml_text = yaml.safe_dump(
        ordered, sort_keys=False, allow_unicode=True, default_flow_style=False, width=10_000,
    ).rstrip("\n")
    return f"{STATE_RATIONALE_HEADING}\n\n```yaml\n{yaml_text}\n```\n"


def upsert_state_rationale_section(body: str, mapping: Mapping[str, Any]) -> str:
    """Insert or replace the ``## State rationale`` section in ``body`` (R3).

    A present section is replaced in place. An absent section is inserted
    immediately before the second top-level ``## ``/``# `` heading (i.e.
    right after the spec's first section, conventionally ``## Problem``), or
    appended at the end when the body has at most one such heading.
    """
    rendered = render_state_rationale_section(mapping)
    span = _state_rationale_section_span(body)
    if span is not None:
        start, end = span
        remainder = body[end:]
        return body[:start] + rendered + ("\n" if remainder and not remainder.startswith("\n") else "") + remainder
    headings = list(_NEXT_HEADING_RE.finditer(body))
    if len(headings) >= 2:
        insert_at = headings[1].start()
        return body[:insert_at] + rendered + "\n" + body[insert_at:]
    if body.strip():
        separator = "" if body.endswith("\n\n") else ("\n" if body.endswith("\n") else "\n\n")
        return body + separator + rendered
    return "\n" + rendered


def evidence_quality_label(frontmatter: Mapping[str, Any], section: Mapping[str, Any] | None) -> str:
    """R5: an honest, derived evidence-quality label -- never a stored `provenance`.

    A present section whose declared ``status`` still matches the spec's
    current frontmatter ``status`` is ``current``. Its absence is
    ``legacy_missing`` -- an honest fact about missing history predating this
    contract, not a promotion signal and never automatically resolved.
    Deliberately presence-based rather than a ``template_version`` numeric
    threshold: template families (main, bugfix, analysis, research, ...) each
    keep an independent version counter (SPEC-GUIDE.md § Spec Types), so no
    single cross-family number reliably marks "this spec predates the
    section".

    A present section whose ``status`` no longer matches the current
    frontmatter ``status`` is ``stale`` (R1's named derived label) rather
    than ``current`` -- this is the R3 case where a caller's transition
    intentionally left the section uncaptured (e.g. ``reconsider_when`` was
    not supplied for a draft/planned/blocked target): the write must never
    read back as an honest, up-to-date declaration. Deeper malformed/
    unavailable classification is SPEC-358/359's concern (static validation
    and live admission), not captured here.
    """
    if section is None:
        return "legacy_missing"
    section_status = section.get("status")
    frontmatter_status = frontmatter.get("status")
    if section_status != frontmatter_status:
        return "stale"
    return "current"


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


# ---------------------------------------------------------------------------
# SPEC-359: one versioned, read-only explanation of the current run state.
#
# This section DESCRIBES results that the existing producers already computed
# (``derive_admission``, the board's authorization overlay, and parallel
# admission's decision). It never decides readiness, never writes, and never
# changes gate precedence: the gate walk below re-reads the very same inputs in
# the producer's own order and is cross-checked against the displayed state; a
# disagreement becomes a diagnostic, never a silent correction.
# ---------------------------------------------------------------------------
EXPLANATION_SCHEMA_VERSION = 1
SUMMARY_STRING_LIMIT = 240
_LIST_BOUND = 25
_TEXT_BOUND = 1000

PERSISTENCE_STATES = ("committed", "staged", "working_tree_only", "private_local", "unknown")
RATIONALE_QUALITIES = (
    "recorded", "reconstructed", "legacy_missing", "stale", "malformed", "unavailable",
)
GATE_RESULTS = ("pass", "fail", "not_evaluated", "unknown")
EXPLANATION_SOURCES = (
    "lifecycle", "intrinsic_readiness", "admission", "parallel_admission",
    "deployment_authorization", "lifecycle_evidence",
)
# Terminal lifecycle records and the NFR-family statuses: never admitted.
NON_ADMISSION_STATUSES = frozenset({"done", "superseded", "active", "retired"})
_ADMISSION_FAMILY_EXCLUDED_TYPES = frozenset({"main", "questions", "nfr"})
# The producer's own generic status-mapping reasons: they explain the mapping,
# never the historical decision (SPEC-357 Problem).
GENERIC_RUN_STATE_REASONS = frozenset({
    "explicitly planned for later", "draft specification",
    "all deterministic admission gates passed",
})
# Parallel admission's decision reasons that name a registered run state.
PARALLEL_REASON_RUN_STATES = {
    "dependency_cycle": "dependency_cycle",
    "surface_overlap": "overlap_conflict",
}

RUN_STATE_MEANINGS = {
    "runnable": "Every admission gate that was evaluated passed; the spec is eligible to be started. "
                "It does not mean a worker has been started or that capacity or overlap are cleared.",
    "specification_incomplete": "The spec is still a draft: its scope or acceptance criteria are not yet "
                                "declared complete, so it cannot be admitted.",
    "intentionally_future": "The author set the lifecycle status to planned: validated work deliberately "
                            "held outside the current queue. This is an authored choice, not a live wait.",
    "validation_failed": "A deterministic check failed (intrinsic readiness or dependency resolution); "
                         "the spec cannot be admitted until the finding is corrected.",
    "review_required": "Intrinsic readiness needs review (for example an unresolved marker); a human "
                       "must resolve it before the spec can be admitted.",
    "waiting_dependencies": "One or more prerequisite specs are not done yet.",
    "waiting_external_input": "The spec declares an external input that must arrive first.",
    "time_gated": "The spec declares a not_before time gate. Admission gates on the field being present, "
                  "not on the time having passed.",
    "overlap_conflict": "The spec declares an overlap conflict, or parallel admission found an "
                        "overlapping surface, with another spec.",
    "dependency_cycle": "Parallel admission found the spec inside a dependency cycle, so it can never "
                        "become runnable until the cycle is broken.",
    "resource_gated": "The spec declares a resource gate that must be released first.",
    "waiting_gap_spec": "The spec declares a gap spec that must be completed first.",
    "awaiting_authorization": "A completed, verified candidate is held before merge in an authorize "
                              "deployment environment until a human authorization record covers its SHA.",
}
# The authoritative producer for each state when it is the decisive result.
RUN_STATE_SOURCES = {
    "runnable": "admission", "specification_incomplete": "lifecycle",
    "intentionally_future": "lifecycle", "validation_failed": "intrinsic_readiness",
    "review_required": "intrinsic_readiness", "waiting_dependencies": "admission",
    "waiting_external_input": "admission", "time_gated": "admission",
    "overlap_conflict": "admission", "dependency_cycle": "parallel_admission",
    "resource_gated": "admission", "waiting_gap_spec": "admission",
    "awaiting_authorization": "deployment_authorization",
}
# Controlled reason-code vocabulary. Producer-specific codes are added here,
# not as separate state enums.
EXPLANATION_REASON_CODES = frozenset({
    "admission_gates_passed", "draft_specification", "planned_for_later",
    "readiness_failed", "readiness_review", "declared_external_input", "declared_not_before",
    "declared_resource_gate", "declared_overlap_conflict", "declared_gap_spec",
    "dependency_resolution_failed", "dependencies_unfinished", "dependency_cycle",
    "authorization_hold", "blocked_by_recorded_blocker", "in_progress", "completed",
    "superseded", "nfr_constraint", "main_container", "questions_record",
    "unregistered_status", "admission_unavailable", "unregistered_run_state",
    "explanation_unavailable",
})


def _clip(text: Any, limit: int = _TEXT_BOUND) -> str:
    value = str(text)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _spec_locator(spec_id: str, project: Any = None) -> dict[str, str]:
    locator = {"kind": "spec", "id": str(spec_id)}
    if project:
        locator["project"] = str(project)
    return locator


def _gate(code: str, result: str, reason: str, evidence: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    return {
        "code": code, "result": result, "reason": _clip(reason),
        "evidence": [dict(item) for item in list(evidence)[:_LIST_BOUND]],
    }


def _diagnostic(code: str, reason: str, evidence: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    return {"code": code, "reason": _clip(reason),
            "evidence": [dict(item) for item in list(evidence)[:_LIST_BOUND]]}


def _parse_declared_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


_SPEC_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+(?:-\d+)*\b")


def _referenced_spec_ids(value: Any, known: Mapping[str, Any] | None) -> list[str]:
    """Spec-shaped IDs named by a declared field, kept only when they resolve if we can tell."""
    text = " ".join(str(item) for item in value) if isinstance(value, (list, tuple)) else str(value)
    found = list(dict.fromkeys(_SPEC_ID_RE.findall(text)))
    if known is not None:
        found = [item for item in found if item in known]
    return found[:_LIST_BOUND]


def _dependency_view(dep: str, specs: Mapping[str, Mapping[str, Any]] | None) -> tuple[str, dict[str, str]]:
    record = (specs or {}).get(dep)
    project = record.get("_external_project") if isinstance(record, Mapping) else None
    status = str(record.get("status")) if isinstance(record, Mapping) and record.get("status") else "not found"
    return status, _spec_locator(dep, project)


class _Ctx:
    """The one bundle of already-computed inputs an adapter may read."""

    def __init__(self, frontmatter: Mapping[str, Any], admission: AdmissionResult | None,
                 specs: Mapping[str, Mapping[str, Any]] | None,
                 dependency_errors: Mapping[str, str] | None,
                 authorization_hold: Mapping[str, Any] | None,
                 parallel_decision: Mapping[str, Any] | None,
                 qualified: Mapping[str, Any] | None, now: datetime) -> None:
        self.fm = frontmatter
        self.spec_id = str(frontmatter.get("id", ""))
        self.status = str(frontmatter.get("status", ""))
        self.admission = admission
        self.specs = specs
        self.dependency_errors = dependency_errors
        self.hold = authorization_hold
        self.parallel = parallel_decision
        self.qualified = qualified
        self.now = now
        self.diagnostics: list[dict[str, Any]] = []
        self.gates: list[dict[str, Any]] = []
        self.decisive: dict[str, Any] | None = None
        self.predicted: str | None = None
        self.reconsider_when: str | None = None


def _readiness_reason(admission: AdmissionResult) -> str:
    failing = [d for d in admission.readiness.dimensions if d.level is not Readiness.PASS]
    if not failing:
        return "all intrinsic readiness dimensions passed"
    return "; ".join(f"{d.name} {d.level.value}: {', '.join(d.evidence)}" for d in failing)


def _walk_admission_gates(ctx: _Ctx) -> None:
    """Describe each gate in ``derive_admission``'s own order (R2).

    A gate after the decisive one is ``not_evaluated``: the producer returned
    before reaching it. A gate the producer could not run for lack of input
    (no dependency snapshot) is ``not_evaluated`` as well -- never ``pass``.
    """
    fm, admission = ctx.fm, ctx.admission
    decided: str | None = None

    def decide(state: str, gate: dict[str, Any]) -> None:
        nonlocal decided
        decided = state
        ctx.predicted = state
        ctx.decisive = gate

    # 1. lifecycle status short-circuits draft/planned before readiness.
    if ctx.status == "draft":
        gate = _gate("lifecycle_status", "fail", "status is draft: the specification is not declared complete")
        decide("specification_incomplete", gate)
    elif ctx.status == "planned":
        gate = _gate("lifecycle_status", "fail",
                     "status is planned: the author placed this work outside the current queue")
        decide("intentionally_future", gate)
    else:
        gate = _gate("lifecycle_status", "pass", f"status {ctx.status or 'unset'} allows admission to be evaluated")
    ctx.gates.append(gate)

    # 2. intrinsic readiness.
    level = admission.readiness.level if admission else None
    informational = f"informational readiness {level.value}" if level else "readiness unavailable"
    if decided:
        ctx.gates.append(_gate("intrinsic_readiness", "not_evaluated",
                               f"not consulted: the lifecycle status decided first ({informational})"))
    elif admission is None:
        ctx.gates.append(_gate("intrinsic_readiness", "unknown", "no admission result was supplied"))
    elif level is Readiness.FAIL:
        gate = _gate("intrinsic_readiness", "fail", _readiness_reason(admission))
        ctx.gates.append(gate)
        decide("validation_failed", gate)
    elif level is Readiness.REVIEW:
        gate = _gate("intrinsic_readiness", "fail", _readiness_reason(admission))
        ctx.gates.append(gate)
        decide("review_required", gate)
    else:
        ctx.gates.append(_gate("intrinsic_readiness", "pass", _readiness_reason(admission)))

    # 3. declared holds, in the producer's precedence order.
    for key, state in DECLARED_HOLD_GATES:
        code = f"declared_{key}"
        if decided:
            ctx.gates.append(_gate(code, "not_evaluated", "not consulted: an earlier gate decided first"))
            continue
        value = fm.get(key)
        if not value:
            ctx.gates.append(_gate(code, "pass", f"{key} is not declared"))
            continue
        evidence = [_spec_locator(item) for item in _referenced_spec_ids(value, ctx.specs)]
        reason = f"declared {key}: {_clip(value, 300)}"
        if key == "not_before":
            declared_at = _parse_declared_time(value)
            if declared_at is not None and declared_at <= ctx.now:
                ctx.diagnostics.append(_diagnostic(
                    "time_gate_elapsed",
                    f"declared not_before {value} has elapsed (now {ctx.now.isoformat()}) but admission "
                    "still gates on the field being present; the field must be removed to clear it",
                    evidence,
                ))
                reason += " (declared time has elapsed; the producer still gates on field presence)"
        gate = _gate(code, "fail", reason, evidence)
        ctx.gates.append(gate)
        decide(state, gate)

    # 4. dependency resolution errors (validation_failed).
    after = fm.get("after") if isinstance(fm.get("after"), list) else []
    if decided:
        ctx.gates.append(_gate("dependency_resolution", "not_evaluated",
                               "not consulted: an earlier gate decided first"))
    elif ctx.dependency_errors is None:
        ctx.gates.append(_gate("dependency_resolution", "not_evaluated",
                               "no dependency resolution snapshot was supplied; absence is not a pass"))
    else:
        failing = [dep for dep in after if dep in ctx.dependency_errors]
        if failing:
            gate = _gate(
                "dependency_resolution", "fail",
                "; ".join(str(ctx.dependency_errors[dep]) for dep in failing),
                [_spec_locator(dep) for dep in failing],
            )
            ctx.gates.append(gate)
            decide("validation_failed", gate)
        else:
            ctx.gates.append(_gate("dependency_resolution", "pass",
                                   f"{len(after)} declared prerequisite(s) resolved without error"))

    # 5. prerequisite states (waiting_dependencies).
    if decided:
        ctx.gates.append(_gate("dependency_states", "not_evaluated",
                               "not consulted: an earlier gate decided first"))
    elif ctx.specs is None:
        ctx.gates.append(_gate("dependency_states", "not_evaluated",
                               "no prerequisite state snapshot was supplied; the producer skips this "
                               "check without one, so absence is not a pass"))
    else:
        unmet, evidence = [], []
        for dep in after:
            status, locator = _dependency_view(dep, ctx.specs)
            if dep not in ctx.specs or ctx.specs[dep].get("status") != "done":
                unmet.append(f"{dep} ({status})")
                evidence.append(locator)
        if unmet:
            gate = _gate("dependency_states", "fail", "unfinished prerequisites: " + ", ".join(unmet), evidence)
            ctx.gates.append(gate)
            decide("waiting_dependencies", gate)
        else:
            ctx.gates.append(_gate(
                "dependency_states", "pass",
                f"all {len(after)} prerequisite(s) are done" if after else "no prerequisites declared",
                [_dependency_view(dep, ctx.specs)[1] for dep in after],
            ))
    if decided is None:
        ctx.predicted = "runnable"


def _qualified_gate(ctx: _Ctx) -> dict[str, Any] | None:
    """requires_specs prerequisites: evaluated by parallel admission, not by ``derive_admission``."""
    fm = ctx.fm
    if "requires_specs" not in fm or fm.get("requires_specs") in (None, []):
        return None
    note = "lifecycle admission does not consult requires_specs; parallel admission does"
    qualified = ctx.qualified
    if not qualified:
        return _gate("qualified_dependencies", "not_evaluated", f"{note}; no resolution was supplied")
    errors, statuses = qualified.get("errors") or {}, qualified.get("statuses") or {}
    details = qualified.get("details") or {}
    if errors:
        return _gate("qualified_dependencies", "fail", note + "; " + "; ".join(str(v) for v in errors.values()))
    unmet = [key for key, status in statuses.items() if status != "done"]
    if unmet:
        return _gate("qualified_dependencies", "fail", note + "; " + "; ".join(
            str(details.get(key, key)) for key in unmet))
    return _gate("qualified_dependencies", "pass", note + "; all cross-project prerequisites are done")


def _parallel_gate(ctx: _Ctx) -> dict[str, Any]:
    decision = ctx.parallel
    if decision is None:
        return _gate("parallel_admission", "not_evaluated",
                     "no parallel admission decision was supplied for this snapshot")
    reason = str(decision.get("reason", ""))
    detail = _clip(decision.get("detail", ""), 300)
    disposition = str(decision.get("disposition", ""))
    limit = decision.get("worker_limit")
    scope = f" (worker_limit={limit})" if limit is not None else ""
    evidence = [_spec_locator(item) for item in decision.get("conflicting_spec_ids") or []]
    evidence += [_spec_locator(item) for item in decision.get("cycle_members") or []
                 if item != ctx.spec_id]
    if decision.get("blocking_ancestor"):
        evidence.append(_spec_locator(decision["blocking_ancestor"]))
    text = f"{disposition}: {reason} -- {detail}{scope}"
    if decision.get("conflicting_surfaces"):
        text += "; surfaces: " + ", ".join(str(item) for item in decision["conflicting_surfaces"][:10])
    if decision.get("cycle_members"):
        text += "; cycle members: " + ", ".join(str(item) for item in decision["cycle_members"][:_LIST_BOUND])
    return _gate("parallel_admission", "pass" if disposition == "admitted" else "fail", text, evidence)


def _parallel_note(ctx: _Ctx) -> str:
    gate = next((g for g in ctx.gates if g["code"] == "parallel_admission" and g["result"] == "fail"), None)
    return f" Parallel admission currently reports: {gate['reason']}" if gate else ""


def _decisive_ids(ctx: _Ctx) -> list[str]:
    return [item["id"] for item in (ctx.decisive or {}).get("evidence", []) if item.get("kind") == "spec"]


def _declared_next(key: str, what: str):
    def adapt(ctx: _Ctx) -> tuple[str, str, str]:
        value = _clip(ctx.fm.get(key), 200)
        return (f"declared_{key}", "admission",
                f"The declared {key} ({value}) must be satisfied and the field removed; {what}")
    return adapt


def _adapt_runnable(ctx: _Ctx):
    return ("admission_gates_passed", "admission",
            "No admission gate that was evaluated is failing; the spec waits for kickoff." + _parallel_note(ctx))


def _adapt_specification_incomplete(ctx: _Ctx):
    trigger = ctx.reconsider_when
    return ("draft_specification", "lifecycle",
            f"Author-recorded revisit trigger: {_clip(trigger, 300)}" if trigger else
            "Complete the specification and change its lifecycle status; nothing advances a draft automatically.")


def _adapt_intentionally_future(ctx: _Ctx):
    trigger = ctx.reconsider_when
    return ("planned_for_later", "lifecycle",
            f"Author-recorded revisit trigger: {_clip(trigger, 300)}" if trigger else
            "No revisit trigger is recorded; the spec stays planned until a person changes its status.")


def _adapt_validation_failed(ctx: _Ctx):
    if ctx.decisive and ctx.decisive["code"] == "dependency_resolution":
        return ("dependency_resolution_failed", "admission",
                "Repair the unresolved prerequisite reference(s): " + ", ".join(_decisive_ids(ctx)))
    return ("readiness_failed", "intrinsic_readiness", "Correct the intrinsic readiness findings listed in the gates.")


def _adapt_review_required(ctx: _Ctx):
    return ("readiness_review", "intrinsic_readiness",
            "A person must resolve the review findings listed in the gates (for example unresolved markers).")


def _adapt_waiting_dependencies(ctx: _Ctx):
    ids = _decisive_ids(ctx)
    return ("dependencies_unfinished", "admission",
            "These prerequisites must reach status done: " + (", ".join(ids) if ids else "see gates"))


def _adapt_time_gated(ctx: _Ctx):
    value = _clip(ctx.fm.get("not_before"), 200)
    elapsed = any(d["code"] == "time_gate_elapsed" for d in ctx.diagnostics)
    tail = ("the declared time has elapsed but admission still gates on the field being present, "
            "so the field must be removed" if elapsed else
            "admission gates on the field being present, so the field must be removed once it has passed")
    return ("declared_not_before", "admission", f"Declared not_before {value}: {tail}.")


def _adapt_dependency_cycle(ctx: _Ctx):
    members = ((ctx.parallel or {}).get("cycle_members")) or []
    return ("dependency_cycle", "parallel_admission",
            "Break the cycle by removing one prerequisite edge among: "
            + (", ".join(str(item) for item in members) if members else "the members reported by parallel admission"))


def _adapt_awaiting_authorization(ctx: _Ctx):
    hold = ctx.hold or {}
    sha = hold.get("candidate_sha") or "the candidate SHA"
    env = f" for environment {hold['environment']}" if hold.get("environment") else ""
    return ("authorization_hold", "deployment_authorization",
            f"A human authorization record covering {sha}{env} must be recorded; "
            "the merge gate re-checks the live candidate itself.")


# The adapter registry IS the coverage contract: the test compares its key set
# to ``RUN_STATES``, so a state added without an adapter fails loudly.
RUN_STATE_ADAPTERS = {
    "runnable": _adapt_runnable,
    "specification_incomplete": _adapt_specification_incomplete,
    "intentionally_future": _adapt_intentionally_future,
    "validation_failed": _adapt_validation_failed,
    "review_required": _adapt_review_required,
    "waiting_dependencies": _adapt_waiting_dependencies,
    "waiting_external_input": _declared_next("external_input", "nothing supplies it automatically."),
    "time_gated": _adapt_time_gated,
    "overlap_conflict": _declared_next("overlap_conflict", "nothing clears it automatically."),
    "dependency_cycle": _adapt_dependency_cycle,
    "resource_gated": _declared_next("resource_gate", "nothing releases it automatically."),
    "waiting_gap_spec": _declared_next("gap_spec", "the gap spec must be completed first."),
    "awaiting_authorization": _adapt_awaiting_authorization,
}


def _applicability(frontmatter: Mapping[str, Any], status: str, displayed_state: str | None) -> tuple[str, str]:
    """Return ``(applicability, kind)``; ``kind`` names the non-admission explanation."""
    spec_type = frontmatter.get("type")
    if str(frontmatter.get("id", "")).startswith("NFR-") or spec_type == "nfr":
        return "not_applicable", "nfr"
    if spec_type == "questions":
        return "not_applicable", "questions"
    if spec_type == "main":
        return "not_applicable", "main"
    if status in ("done", "superseded"):
        return "not_applicable", status
    if status in ("active", "retired"):
        return "not_applicable", "nfr"
    if status == "blocked":
        return "not_applicable", "blocked"
    if status == "in_progress":
        return ("admission", "admission") if displayed_state == "awaiting_authorization" \
            else ("not_applicable", "in_progress")
    if status in ("draft", "planned", "ready"):
        return "admission", "admission"
    return "not_applicable", "unregistered"


_NON_ADMISSION_MEANINGS = {
    "nfr": "A non-functional-requirement record: a constraint other specs are checked against. "
           "It is never scheduled, so no run state applies.",
    "questions": "A QUESTIONS record collecting open decisions. It is never scheduled, so no run state applies.",
    "main": "A main (container) spec that groups other specs. It is never scheduled itself, so no run state applies.",
    "done": "Completed: the acceptance criteria were satisfied. A finished spec is not admitted again, "
            "so no run state applies.",
    "superseded": "Replaced by other work. A superseded spec is never executed, so no run state applies.",
    "blocked": "Stopped by a recorded blocker. Blocked is a lifecycle status, not an admission result: "
               "the spec is not eligible for admission until the blocker is resolved and its status changes.",
    "in_progress": "Work on this spec has started. A fresh admission decision does not apply to a running "
                   "spec; its execution context is shown from the run evidence that is available.",
    "unregistered": "The stored status is not a registered lifecycle status, so no admission result applies.",
}


def _blocker_gate(fm: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors = validate_blocked(fm)
    evidence: list[dict[str, str]] = []
    raw = fm.get("blocker_evidence")
    if isinstance(raw, str) and is_safe_relative_posix_path(raw.strip()):
        evidence.append({"kind": "file", "path": raw.strip()})
    if errors:
        return _gate("blocker_fields", "fail", "; ".join(errors), evidence), evidence
    return _gate("blocker_fields", "pass",
                 f"blocker record is complete (class {fm.get('blocker_class')}, scope {fm.get('blocker_scope')})",
                 evidence), evidence


def _execution_context_gate(run_evidence: Mapping[str, Any] | None, effective: str,
                            diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    """Report the run evidence that exists; never infer liveness from file age or commits."""
    if not run_evidence:
        return _gate("execution_context", "unknown",
                     "no authoritative run evidence is available; liveness is not evaluated")
    parts = []
    checkpoint = run_evidence.get("checkpoint")
    if isinstance(checkpoint, Mapping) and checkpoint.get("status"):
        parts.append(
            f"durable checkpoint status {checkpoint.get('status')}"
            + (f", run {checkpoint['run_id']}" if checkpoint.get("run_id") else "")
            + (f", source {checkpoint['source']}" if checkpoint.get("source") else "")
            + (f", recorded {checkpoint['created_at']}" if checkpoint.get("created_at") else "")
        )
        if checkpoint.get("status") != effective:
            diagnostics.append(_diagnostic(
                "status_run_evidence_mismatch",
                f"effective status {effective!r} disagrees with the durable checkpoint status "
                f"{checkpoint.get('status')!r}; neither is corrected here",
            ))
    heartbeat = run_evidence.get("heartbeat")
    if heartbeat:
        parts.append(f"heartbeat result supplied by its owner: {_clip(heartbeat, 200)} (not re-interpreted)")
    if not parts:
        return _gate("execution_context", "unknown", "run evidence carried no usable fields")
    return _gate("execution_context", "pass", "; ".join(parts) + "; liveness is not evaluated")


def _lifecycle_section(frontmatter: Mapping[str, Any], status: str,
                       view: Mapping[str, Any] | None) -> dict[str, Any]:
    base = {"declared": status, "effective": status, "committed": None,
            "source": "frontmatter",
            "sync": {"in_sync": True, "durable": None, "effective": status, "reason": None}}
    if view:
        base.update({key: view[key] for key in base if key in view})
    return base


def _rationale_section(frontmatter: Mapping[str, Any], rationale: Mapping[str, Any] | None,
                       diagnostics: list[dict[str, Any]]) -> dict[str, Any] | None:
    if rationale is None:
        if not requires_state_rationale(frontmatter):
            return None
        diagnostics.append(_diagnostic(
            "rationale_unavailable", "the rationale record was not resolved for this snapshot"))
        return {"quality": "unavailable", "provenance": None, "reason": None,
                "reconsider_when": None, "record": None, "evidence": []}
    diagnostics.extend(dict(item) for item in rationale.get("diagnostics") or [])
    reason = rationale.get("reason")
    if isinstance(reason, str) and reason.strip().lower() in GENERIC_RUN_STATE_REASONS:
        diagnostics.append(_diagnostic(
            "rationale_reason_generic",
            f"the recorded reason {reason!r} is the generic status mapping, not decision provenance"))
    return {
        "quality": rationale.get("quality", "unavailable"),
        "provenance": rationale.get("provenance"),
        "reason": None if reason is None else _clip(reason),
        "reconsider_when": None if rationale.get("reconsider_when") is None
        else _clip(rationale["reconsider_when"]),
        "record": rationale.get("record"),
        "evidence": [dict(item) for item in list(rationale.get("evidence") or [])[:_LIST_BOUND]],
    }


def _persistence_section(persistence: Mapping[str, Any] | None, rationale: Mapping[str, Any] | None) -> dict[str, str]:
    values = dict(persistence or {})
    section = {}
    for key in ("spec", "record", "index"):
        value = values.get(key, "unknown")
        allowed = PERSISTENCE_STATES + (("not_applicable",) if key != "spec" else ())
        section[key] = value if value in allowed else "unknown"
    return section


def _persistence_diagnostics(spec_id: str, lifecycle_section: Mapping[str, Any],
                             persistence: Mapping[str, str], rationale: Mapping[str, Any] | None,
                             notes: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """State the facts about committed-versus-working bytes without asserting a transition."""
    out: list[dict[str, Any]] = []
    known = {k: v for k, v in persistence.items() if v not in ("unknown", "not_applicable")}
    if not known:
        return out
    uncommitted = [k for k, v in known.items() if v in ("staged", "working_tree_only")]
    declared, committed = lifecycle_section["declared"], lifecycle_section["committed"]
    if not uncommitted and (committed in (None, declared)):
        return out
    facts = [f"working spec status {declared!r}",
             f"committed (HEAD) status {committed!r}" if committed is not None else "spec has no committed version"]
    facts += [f"{key}: {value}" for key, value in persistence.items()]
    evidence = [_spec_locator(spec_id)]
    if rationale and rationale.get("record"):
        evidence.append({"kind": "artifact", "spec": spec_id, "path": rationale["record"]})
    out.append(_diagnostic(
        "transition_not_committed",
        "; ".join(facts) + ". The displayed lifecycle state is not shown as a committed transition.",
        evidence))
    if notes and notes.get("partially_staged"):
        out.append(_diagnostic(
            "partially_staged",
            "the index holds an earlier version than the working bytes for: "
            + ", ".join(str(item) for item in notes["partially_staged"]), evidence[:1]))
    return out


def _authorization_gate(ctx: _Ctx) -> dict[str, Any]:
    hold = ctx.hold
    if hold is None:
        return _gate("deployment_authorization", "not_evaluated", "no queue evidence was supplied")
    if not hold.get("held"):
        if hold.get("checked"):
            return _gate("deployment_authorization", "pass",
                         "no held candidate in the integration queue evidence (best-effort read)")
        return _gate("deployment_authorization", "unknown", "queue evidence could not be read")
    evidence = []
    if hold.get("queue_file"):
        evidence.append({"kind": "file", "path": str(hold["queue_file"])})
    if hold.get("authorization_record"):
        evidence.append({"kind": "artifact", "spec": ctx.spec_id, "path": str(hold["authorization_record"])})
    text = str(hold.get("reason") or "awaiting deployment authorization")
    if hold.get("candidate_sha"):
        text += f"; candidate {hold['candidate_sha']}"
    if hold.get("environment"):
        text += f"; environment {hold['environment']}"
    if hold.get("run_id"):
        text += f"; run {hold['run_id']}"
    return _gate("deployment_authorization", "fail", text, evidence)


def run_state_explanation(
    frontmatter: Mapping[str, Any], *,
    admission: AdmissionResult | None = None,
    specs: Mapping[str, Mapping[str, Any]] | None = None,
    dependency_errors: Mapping[str, str] | None = None,
    authorization_hold: Mapping[str, Any] | None = None,
    parallel_decision: Mapping[str, Any] | None = None,
    qualified: Mapping[str, Any] | None = None,
    lifecycle_view: Mapping[str, Any] | None = None,
    rationale: Mapping[str, Any] | None = None,
    persistence: Mapping[str, Any] | None = None,
    persistence_notes: Mapping[str, Any] | None = None,
    run_evidence: Mapping[str, Any] | None = None,
    legacy_run_state: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """SPEC-359 R1: the one read-only explanation of a spec's current run state.

    Every argument is a result some producer already computed for the same
    snapshot; nothing is read, decided or written here. ``admission`` is the
    displayed result (after any authorization overlay).
    """
    when = now or datetime.now(timezone.utc)
    status = str(frontmatter.get("status", ""))
    spec_id = str(frontmatter.get("id", ""))
    displayed_state = admission.state if admission is not None else None
    applicability, kind = _applicability(frontmatter, status, displayed_state)
    ctx = _Ctx(frontmatter, admission, specs, dependency_errors, authorization_hold,
               parallel_decision, qualified, when)
    lifecycle_section = _lifecycle_section(frontmatter, status, lifecycle_view)
    rationale_section = _rationale_section(frontmatter, rationale, ctx.diagnostics)
    ctx.reconsider_when = (
        rationale_section.get("reconsider_when")
        if rationale_section and rationale_section["quality"] in ("recorded", "reconstructed", "unavailable")
        else None
    )
    run_state: str | None = None
    next_condition: str | None = None

    if applicability == "admission":
        _walk_admission_gates(ctx)
        extra = _qualified_gate(ctx)
        if extra:
            ctx.gates.append(extra)
        ctx.gates.append(_parallel_gate(ctx))
        if status == "in_progress" or displayed_state == "awaiting_authorization":
            auth_gate = _authorization_gate(ctx)
            ctx.gates.append(auth_gate)
            if displayed_state == "awaiting_authorization":
                ctx.decisive = auth_gate
        if displayed_state is None:
            primary = {"code": "admission_unavailable", "reason": "no admission result was supplied",
                       "source": "admission"}
            ctx.diagnostics.append(_diagnostic(
                "admission_unavailable", "no admission result was supplied for this applicable spec"))
            meaning = "No admission result was available for this snapshot."
        elif displayed_state not in RUN_STATE_ADAPTERS:
            primary = {"code": "unregistered_run_state",
                       "reason": _clip(f"run state {displayed_state!r} has no registered explanation adapter"),
                       "source": "admission"}
            ctx.diagnostics.append(_diagnostic("unregistered_run_state", primary["reason"]))
            meaning = "This run state is not registered with an explanation adapter."
        else:
            code, source, next_condition = RUN_STATE_ADAPTERS[displayed_state](ctx)
            primary = {"code": code, "reason": _clip(admission.reason), "source": source}
            run_state = displayed_state
            meaning = RUN_STATE_MEANINGS[displayed_state]
            if RUN_STATE_SOURCES[displayed_state] in ("admission", "lifecycle", "intrinsic_readiness") \
                    and ctx.predicted != displayed_state:
                ctx.diagnostics.append(_diagnostic(
                    "gate_walk_disagrees",
                    f"the displayed state {displayed_state!r} differs from the state {ctx.predicted!r} that "
                    "the same inputs give when the gates are re-read in producer order; the displayed "
                    "state is kept"))
        decision_reason = str((parallel_decision or {}).get("reason", ""))
        mapped = PARALLEL_REASON_RUN_STATES.get(decision_reason)
        if mapped and mapped != displayed_state:
            ctx.diagnostics.append(_diagnostic(
                "parallel_admission_differs",
                f"parallel admission reports {decision_reason!r} (state {mapped}) while lifecycle admission "
                f"shows {displayed_state!r}; the two producers are shown separately, neither overrides",
                [_spec_locator(item) for item in (parallel_decision or {}).get("cycle_members") or []
                 if item != spec_id]))
        if displayed_state == "awaiting_authorization" and (authorization_hold or {}).get("authorization_record"):
            ctx.diagnostics.append(_diagnostic(
                "authorization_recorded_since_hold",
                "an authorization record now covers the held candidate; the queue evidence is unchanged "
                "until the merge gate next runs",
                [{"kind": "artifact", "spec": spec_id, "path": str(authorization_hold["authorization_record"])}]))
    else:
        gates: list[dict[str, Any]] = []
        meaning = _NON_ADMISSION_MEANINGS[kind]
        source = "lifecycle"
        if kind == "nfr":
            code, reason = "nfr_constraint", f"{spec_id} is an NFR constraint record (status {status}); it is not scheduled"
        elif kind == "questions":
            code, reason = "questions_record", f"{spec_id} is a QUESTIONS record; it is not scheduled"
        elif kind == "main":
            code, reason = "main_container", f"{spec_id} is a main container spec; it is not scheduled itself"
        elif kind == "done":
            code, reason = "completed", "status done: completed; it is not admitted again"
        elif kind == "superseded":
            code, reason = "superseded", "status superseded: replaced by other work; it is never executed"
            successor = frontmatter.get("superseded_by")
            if successor:
                reason += f" (superseded_by: {_clip(successor, 120)})"
                gates.append(_gate("lifecycle_status", "pass", "declared successor",
                                   [_spec_locator(item) for item in _referenced_spec_ids(successor, None)]))
        elif kind == "blocked":
            source = "lifecycle_evidence"
            code = "blocked_by_recorded_blocker"
            text = str(frontmatter.get("block_reason") or "").strip()
            reason = _clip(text) if text else "status blocked with no recorded block_reason"
            gate, _ = _blocker_gate(frontmatter)
            gates.append(gate)
            unblock = str(frontmatter.get("unblock_condition") or "").strip()
            next_condition = _clip(unblock) if unblock else None
        elif kind == "in_progress":
            source = "lifecycle_evidence"
            code, reason = "in_progress", "status in_progress: work has started; admission does not re-decide a running spec"
            gates.append(_execution_context_gate(run_evidence, status, ctx.diagnostics))
            gates.append(_authorization_gate(ctx))
        else:
            code, reason = "unregistered_status", _clip(f"stored status {status!r} is not a registered lifecycle status")
        gates.insert(0, _gate("admission_gates", "not_evaluated",
                              f"admission does not apply to a {kind.replace('_', ' ')} record"))
        ctx.gates = gates
        primary = {"code": code, "reason": reason, "source": source}
        if legacy_run_state:
            ctx.diagnostics.append(_diagnostic(
                "legacy_run_state_not_admission",
                f"the legacy run_state field shows {legacy_run_state!r}; for this {kind} spec that is a "
                "status mapping, not an admission result, and is not read as runnable"))

    if displayed_state == "awaiting_authorization" and status == "in_progress":
        ctx.gates.insert(0, _execution_context_gate(run_evidence, status, ctx.diagnostics))

    sync = lifecycle_section.get("sync") or {}
    if sync.get("in_sync") is False:
        ctx.diagnostics.append(_diagnostic(
            "status_sync_mismatch",
            f"durable checkpoint status {sync.get('durable')!r} differs from the frontmatter status "
            f"{lifecycle_section['declared']!r}; the effective status {lifecycle_section['effective']!r} "
            f"is shown ({sync.get('reason')})", [_spec_locator(spec_id)]))
    persistence_section = _persistence_section(persistence, rationale)
    ctx.diagnostics.extend(_persistence_diagnostics(
        spec_id, lifecycle_section, persistence_section, rationale_section, persistence_notes))

    return {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "spec_id": spec_id,
        "lifecycle": lifecycle_section,
        "applicability": applicability,
        "run_state": run_state,
        "meaning": meaning,
        "primary": primary,
        "gates": ctx.gates[: _LIST_BOUND * 2],
        "next_condition": next_condition,
        "rationale": rationale_section,
        "persistence": persistence_section,
        "diagnostics": ctx.diagnostics[: _LIST_BOUND * 2],
    }


def run_state_summary(explanation: Mapping[str, Any]) -> dict[str, Any]:
    """SPEC-359 R6: the bounded list-response view, derived from the full projection."""
    truncated: list[str] = []

    def bounded(name: str, value: Any) -> Any:
        if isinstance(value, str) and len(value) > SUMMARY_STRING_LIMIT:
            truncated.append(name)
            return value[: SUMMARY_STRING_LIMIT - 1].rstrip() + "…"
        return value

    rationale = explanation.get("rationale")
    persistence = explanation.get("persistence") or {}
    return {
        "schema_version": explanation.get("schema_version"),
        "applicability": explanation.get("applicability"),
        "run_state": explanation.get("run_state"),
        "meaning": bounded("meaning", explanation.get("meaning")),
        "reason": bounded("reason", (explanation.get("primary") or {}).get("reason")),
        "next_condition": bounded("next_condition", explanation.get("next_condition")),
        "rationale_quality": rationale["quality"] if rationale else "not_applicable",
        "persistence": {key: persistence.get(key, "unknown") for key in ("spec", "record", "index")},
        "truncated_fields": truncated,
    }


def unavailable_run_state_explanation(spec_id: str, status: str, reason: str) -> dict[str, Any]:
    """The explanation for one spec whose derivation failed: it affects only that spec (R6)."""
    unknown = {"in_sync": True, "durable": None, "effective": status, "reason": None}
    return {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "spec_id": spec_id,
        "lifecycle": {"declared": status, "effective": status, "committed": None,
                      "source": "frontmatter", "sync": unknown},
        "applicability": "not_applicable",
        "run_state": None,
        "meaning": "The explanation for this spec could not be derived; the legacy run_state fields are unaffected.",
        "primary": {"code": "explanation_unavailable", "reason": _clip(reason), "source": "lifecycle"},
        "gates": [_gate("explanation", "unknown", reason)],
        "next_condition": None,
        "rationale": {"quality": "unavailable", "provenance": None, "reason": None,
                      "reconsider_when": None, "record": None, "evidence": []},
        "persistence": {"spec": "unknown", "record": "unknown", "index": "unknown"},
        "diagnostics": [_diagnostic("explanation_unavailable", reason)],
    }
