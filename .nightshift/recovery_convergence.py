"""Source-specific admission for implementer-blocked SPEC-235 recovery.

This module validates and classifies implementer evidence.  It deliberately
does not own lifecycle, dispatch, integration, or verification; admitted
assessments are consumed by the existing ``verifier_feedback`` reducer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
MAX_ENVELOPE_BYTES = 32_768
MAX_ITEMS = 64
MAX_TOKEN_LENGTH = 256
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40,64}")
IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
AC_RE = re.compile(r"AC[1-9][0-9]*")
FORBIDDEN_TEXT_RE = re.compile(
    r"(?:https?://|file://|/Users/|/home/|\\Users\\|\$|`|\n|\r|"
    r"password|passwd|secret|credential_value|api[_-]?key|access[_-]?token|"
    r"environment|username|prompt|raw[_ -]?output|stdout|stderr)",
    re.IGNORECASE,
)

BLOCKER_FACTS = frozenset({
    "implementation_gap", "test_runner_missing", "fixture_schema_mismatch",
    "missing_verification_artifact", "credential_required",
    "external_approval_required", "destructive_authority_required",
    "protected_scope_required", "safe_uncertainty", "unclear_causality",
})
INTERVENTIONS = frozenset({
    "focused_test_rerun", "dependency_probe", "fixture_refresh_probe",
    "artifact_inventory", "none",
})
CHANGE_KINDS = frozenset({"added", "modified", "deleted", "renamed"})
CONFIDENCE = frozenset({"demonstrated", "supported", "uncertain"})


class RecoveryConvergenceError(ValueError):
    """Implementer-blocked evidence or routing failed closed."""


class DiagnosisClass(str, Enum):
    IN_SCOPE_IMPLEMENTATION = "in_scope_implementation"
    TEST_INFRASTRUCTURE = "test_infrastructure"
    FIXTURE_DRIFT = "fixture_drift"
    EVIDENCE_GAP = "evidence_gap"
    EXTERNAL_INPUT = "external_input"
    SAFETY_OR_SCOPE = "safety_or_scope"
    AMBIGUOUS = "ambiguous"


class RepairRoute(str, Enum):
    RESUME_ORIGINAL = "resume_original"
    FRESH_SPECIALIST = "fresh_specialist"


@dataclass(frozen=True)
class ArtifactReference:
    path: str
    sha256: str


@dataclass(frozen=True)
class PartialWorkItem:
    path: str
    sha256: str
    ac_ids: tuple[str, ...]
    change_kind: str


@dataclass(frozen=True)
class BlockedAttemptDiagnosis:
    schema_version: int
    packet_type: str
    run_id: str
    spec_id: str
    candidate_revision: str
    implementation_head_digest: str
    attempted_ac_ids: tuple[str, ...]
    untouched_ac_ids: tuple[str, ...]
    partial_work: tuple[PartialWorkItem, ...]
    blocker_facts: tuple[str, ...]
    earlier_interventions: tuple[str, ...]
    reproducible_probes: tuple[tuple[str, ...], ...]
    original_authority: tuple[str, ...]
    artifact_refs: tuple[ArtifactReference, ...]

    def record(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "attempted_ac_ids", "untouched_ac_ids", "blocker_facts",
            "earlier_interventions", "original_authority",
        ):
            value[key] = list(getattr(self, key))
        value["partial_work"] = [
            {**asdict(item), "ac_ids": list(item.ac_ids)} for item in self.partial_work
        ]
        value["reproducible_probes"] = [list(probe) for probe in self.reproducible_probes]
        value["artifact_refs"] = [asdict(item) for item in self.artifact_refs]
        return value

    def digest(self) -> str:
        return _digest(self.record())


@dataclass(frozen=True)
class SmallestNextTask:
    files: tuple[str, ...]
    ac_ids: tuple[str, ...]
    capability: str
    probes: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class BlockedAttemptAssessment:
    source: str
    candidate_revision: str
    classification: DiagnosisClass
    facts: tuple[str, ...]
    confidence: str
    eligible: bool
    diagnostician_required: bool
    next_task: SmallestNextTask | None
    operator_action: str

    def record(self) -> dict[str, Any]:
        value = asdict(self)
        value["classification"] = self.classification.value
        value["facts"] = list(self.facts)
        if self.next_task is not None:
            value["next_task"]["files"] = list(self.next_task.files)
            value["next_task"]["ac_ids"] = list(self.next_task.ac_ids)
            value["next_task"]["probes"] = [list(item) for item in self.next_task.probes]
        return value

    def digest(self) -> str:
        return _digest(self.record())


@dataclass(frozen=True)
class RepairSelection:
    route: RepairRoute
    files: tuple[str, ...]
    ac_ids: tuple[str, ...]
    capability: str
    probes: tuple[tuple[str, ...], ...]


def _digest(value: Mapping[str, Any]) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode()).hexdigest()


def _safe_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN_LENGTH:
        raise RecoveryConvergenceError(f"invalid {label}")
    if FORBIDDEN_TEXT_RE.search(value):
        raise RecoveryConvergenceError(f"unsafe {label}")
    return value


def _relative_path(value: Any, label: str) -> str:
    text = _safe_text(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or text.startswith(("~", ".git/")):
        raise RecoveryConvergenceError(f"unsafe {label}")
    return text


def _closed(data: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(data) != fields:
        raise RecoveryConvergenceError(f"{label} fields do not match the closed schema")


def _bounded_list(value: Any, label: str, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS or (not value and not allow_empty):
        raise RecoveryConvergenceError(f"invalid {label}")
    return value


def blocked_attempt_from_dict(
    data: Mapping[str, Any], *, run_id: str, spec_id: str,
    candidate_revision: str, implementation_head_digest: str,
    known_ac_ids: Iterable[str], changed_paths: Iterable[str],
) -> BlockedAttemptDiagnosis:
    """Validate a complete, identity-bound blocker envelope before actor dispatch."""
    if not isinstance(data, Mapping):
        raise RecoveryConvergenceError("blocked attempt must be an object")
    if len(json.dumps(data, sort_keys=True, ensure_ascii=True).encode()) > MAX_ENVELOPE_BYTES:
        raise RecoveryConvergenceError("blocked attempt exceeds maximum size")
    fields = {
        "schema_version", "packet_type", "run_id", "spec_id", "candidate_revision",
        "implementation_head_digest", "attempted_ac_ids", "untouched_ac_ids",
        "partial_work", "blocker_facts", "earlier_interventions",
        "reproducible_probes", "original_authority", "artifact_refs",
    }
    _closed(data, fields, "blocked attempt")
    if data["schema_version"] != SCHEMA_VERSION or data["packet_type"] != "blocked_attempt_diagnosis":
        raise RecoveryConvergenceError("unsupported blocked attempt schema")
    for actual, expected, label in (
        (data["run_id"], run_id, "run identity"),
        (data["spec_id"], spec_id, "spec identity"),
        (data["candidate_revision"], candidate_revision, "candidate revision"),
        (data["implementation_head_digest"], implementation_head_digest, "implementation digest"),
    ):
        if actual != expected:
            raise RecoveryConvergenceError(f"stale {label}")
    if not IDENTITY_RE.fullmatch(run_id) or not IDENTITY_RE.fullmatch(spec_id):
        raise RecoveryConvergenceError("invalid blocked attempt identity")
    if not GIT_OBJECT_ID_RE.fullmatch(candidate_revision) or not SHA256_RE.fullmatch(implementation_head_digest):
        raise RecoveryConvergenceError("invalid blocked attempt digest")

    attempted = tuple(_bounded_list(data["attempted_ac_ids"], "attempted AC IDs", allow_empty=True))
    untouched = tuple(_bounded_list(data["untouched_ac_ids"], "untouched AC IDs", allow_empty=True))
    expected = set(known_ac_ids)
    if (
        any(not isinstance(item, str) or not AC_RE.fullmatch(item) for item in (*attempted, *untouched))
        or set(attempted) & set(untouched)
        or set(attempted) | set(untouched) != expected
        or len(attempted) != len(set(attempted))
        or len(untouched) != len(set(untouched))
    ):
        raise RecoveryConvergenceError("unknown or incomplete AC inventory")

    authority = tuple(
        _relative_path(item, "original authority")
        for item in _bounded_list(data["original_authority"], "original authority")
    )
    work: list[PartialWorkItem] = []
    for raw in _bounded_list(data["partial_work"], "partial work", allow_empty=True):
        if not isinstance(raw, Mapping):
            raise RecoveryConvergenceError("invalid partial work item")
        _closed(raw, {"path", "sha256", "ac_ids", "change_kind"}, "partial work item")
        path = _relative_path(raw["path"], "partial work path")
        if not SHA256_RE.fullmatch(str(raw["sha256"])):
            raise RecoveryConvergenceError("invalid partial work digest")
        ac_ids = tuple(_bounded_list(raw["ac_ids"], "partial work AC IDs"))
        if not set(ac_ids) <= expected or raw["change_kind"] not in CHANGE_KINDS:
            raise RecoveryConvergenceError("invalid partial work binding")
        if not any(_within(path, root) for root in authority):
            raise RecoveryConvergenceError("partial work exceeds original authority")
        work.append(PartialWorkItem(path, str(raw["sha256"]), ac_ids, str(raw["change_kind"])))
    observed_changed = {_relative_path(item, "changed path") for item in changed_paths}
    if len({item.path for item in work}) != len(work) or {
        item.path for item in work
    } != observed_changed:
        raise RecoveryConvergenceError("unbound changed paths")

    facts = tuple(_bounded_list(data["blocker_facts"], "blocker facts"))
    if any(_safe_text(item, "blocker fact") not in BLOCKER_FACTS for item in facts):
        raise RecoveryConvergenceError("unknown blocker fact")
    interventions = tuple(_bounded_list(data["earlier_interventions"], "earlier interventions"))
    if any(_safe_text(item, "earlier intervention") not in INTERVENTIONS for item in interventions):
        raise RecoveryConvergenceError("unknown earlier intervention")
    probes: list[tuple[str, ...]] = []
    for raw in _bounded_list(data["reproducible_probes"], "reproducible probes"):
        probes.append(tuple(_safe_text(token, "probe token") for token in _bounded_list(raw, "probe argv")))
    refs: list[ArtifactReference] = []
    for raw in _bounded_list(data["artifact_refs"], "artifact refs", allow_empty=True):
        if not isinstance(raw, Mapping):
            raise RecoveryConvergenceError("invalid artifact reference")
        _closed(raw, {"path", "sha256"}, "artifact reference")
        path = _relative_path(raw["path"], "artifact path")
        if not SHA256_RE.fullmatch(str(raw["sha256"])):
            raise RecoveryConvergenceError("invalid artifact digest")
        refs.append(ArtifactReference(path, str(raw["sha256"])))
    return BlockedAttemptDiagnosis(
        SCHEMA_VERSION, "blocked_attempt_diagnosis", run_id, spec_id,
        candidate_revision, implementation_head_digest, attempted, untouched,
        tuple(work), facts, interventions, tuple(probes), authority, tuple(refs),
    )


def _within(path: str, root: str) -> bool:
    child, parent = PurePosixPath(path), PurePosixPath(root)
    return child == parent or parent in child.parents


def assess_blocked_attempt(packet: BlockedAttemptDiagnosis) -> BlockedAttemptAssessment:
    """Classify mechanical facts; only safe uncertainty requests a read-only actor."""
    facts = set(packet.blocker_facts)
    if facts & {"credential_required", "external_approval_required"}:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.EXTERNAL_INPUT, "demonstrated", False, False, "provide_external_input"
        )
    elif facts & {"destructive_authority_required", "protected_scope_required"}:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.SAFETY_OR_SCOPE, "demonstrated", False, False, "authorize_scope"
        )
    elif facts == {"implementation_gap"}:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.IN_SCOPE_IMPLEMENTATION, "demonstrated", True, False, "dispatch_repair"
        )
    elif facts == {"test_runner_missing"}:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.TEST_INFRASTRUCTURE, "demonstrated", True, False, "dispatch_repair"
        )
    elif facts == {"fixture_schema_mismatch"}:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.FIXTURE_DRIFT, "demonstrated", True, False, "dispatch_repair"
        )
    elif facts == {"missing_verification_artifact"}:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.EVIDENCE_GAP, "supported", True, False, "dispatch_repair"
        )
    elif facts == {"safe_uncertainty"}:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.AMBIGUOUS, "uncertain", False, True, "dispatch_read_only_diagnostician"
        )
    else:
        classification, confidence, eligible, diagnostic, action = (
            DiagnosisClass.AMBIGUOUS, "uncertain", False, False, "operator_controller_action"
        )
    task = None
    if eligible or diagnostic:
        capability = {
            DiagnosisClass.TEST_INFRASTRUCTURE: "test_infrastructure",
            DiagnosisClass.FIXTURE_DRIFT: "fixture_maintenance",
            DiagnosisClass.EVIDENCE_GAP: "evidence_generation",
            DiagnosisClass.AMBIGUOUS: "read_only_diagnosis",
        }.get(classification, "implementation")
        task = SmallestNextTask(
            packet.original_authority,
            packet.untouched_ac_ids or packet.attempted_ac_ids,
            capability,
            packet.reproducible_probes,
        )
    return BlockedAttemptAssessment(
        "implementer_blocked", packet.candidate_revision, classification,
        packet.blocker_facts, confidence, eligible, diagnostic, task, action,
    )


def select_repair_route(
    assessment: BlockedAttemptAssessment, *, route: str, files: Iterable[str],
    ac_ids: Iterable[str], capability: str, active_surfaces: Iterable[str],
) -> RepairSelection:
    """Validate exactly one bounded repair route without authority growth/overlap."""
    if not assessment.eligible or assessment.next_task is None:
        raise RecoveryConvergenceError("assessment is not repair eligible")
    try:
        selected = RepairRoute(route)
    except ValueError as exc:
        raise RecoveryConvergenceError("invalid or dual repair route") from exc
    bounded_files = tuple(_relative_path(item, "repair file") for item in files)
    bounded_acs = tuple(ac_ids)
    if not bounded_files or any(
        not any(_within(path, root) for root in assessment.next_task.files)
        for path in bounded_files
    ):
        raise RecoveryConvergenceError("repair grows original authority")
    if not bounded_acs or not set(bounded_acs) <= set(assessment.next_task.ac_ids):
        raise RecoveryConvergenceError("repair grows AC authority")
    if capability != assessment.next_task.capability:
        raise RecoveryConvergenceError("repair capability mismatch")
    for active in active_surfaces:
        active_path = _relative_path(active, "active surface")
        if any(_within(path, active_path) or _within(active_path, path) for path in bounded_files):
            raise RecoveryConvergenceError("repair overlaps active work")
    return RepairSelection(
        selected, bounded_files, bounded_acs, capability, assessment.next_task.probes
    )
