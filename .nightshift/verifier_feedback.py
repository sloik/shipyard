"""Controlled verifier-remediation feedback for a Nightshift kickoff parent.

The module is deliberately provider neutral.  It validates a failing independent
verdict, creates one immutable parent-signed packet, and reduces normalized
events into durable keyed effects.  Runtime adapters execute effects; they do
not decide lifecycle, eligibility, verification, or integration policy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from verification_report import (
    VERIFIER_IDENTITY_SCHEMA_VERSION,
    validate_dispatch_identity,
    validate_verifier_verdict_dict,
)
from lifecycle import attempt_requires_delivery_assessment
from recovery_convergence import (
    BlockedAttemptAssessment,
    BlockedAttemptDiagnosis,
    DiagnosisClass,
    RecoveryConvergenceError,
    RepairRoute,
    RepairSelection,
    assess_blocked_attempt,
    blocked_attempt_from_dict,
    select_repair_route,
)
from resilience_ladder import ResilienceDecision, decide_verifier_fail

PACKET_SCHEMA_VERSION = 2
MAX_PACKET_BYTES = 32_768
MAX_ITEMS = 64
MAX_TOKEN_LENGTH = 256
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40,64}")
IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
AC_RE = re.compile(r"AC[1-9][0-9]*")
PRIVATE_PATH_PARTS = frozenset({"private", ".private", "_private"})
FORBIDDEN_TEXT_RE = re.compile(
    r"(?:https?://|file://|/Users/|/home/|\\Users\\|\$\{|`|\$\(|\n|\r|"
    r"password|passwd|secret|credential|api[_-]?key|access[_-]?token|"
    r"environment|username|prompt|raw[_ -]?output|log(?:s|file)?)",
    re.IGNORECASE,
)
FORBIDDEN_PACKET_KEYS = frozenset(
    {
        "raw_output",
        "logs",
        "log",
        "prompt",
        "prompts",
        "environment",
        "env",
        "credentials",
        "username",
        "url",
        "secret",
        "stderr",
        "stdout",
    }
)
CAUSAL_CONFIDENCE = frozenset({"demonstrated", "supported", "not_established"})
REMEDIATION_MODES = frozenset({"resume_original", "fresh_worker"})
ACTOR_ROLES = frozenset({
    "implementer", "diagnostician", "repairer", "verifier", "remediator", "parent"
})
ACTOR_OUTCOMES = frozenset(
    {
        "completed",
        "blocked",
        "refused",
        "failed",
        "stalled",
        "unavailable",
        "passed",
        "cancelled",
    }
)
CONTROLLED_REASONS = frozenset(
    {
        "ordinary_progress",
        "external_input",
        "external_authority",
        "safety_refusal",
        "scope_refusal",
        "budget_exhausted",
        "adapter_failure",
        "invalid_verdict",
        "legacy_verdict_identity",
        "verifier_identity_mismatch",
        "dispatch_failure",
        "unchanged_head",
        "remediation_failure",
        "fresh_verifier_failure",
        "implementer_blocked",
        "ambiguous_blocker",
        "actor_unavailable",
        "repair_rejected",
        "repair_exhausted",
        "unknown_recovery_source",
        "contradictory_duplicate",
    }
)


def _human_action_for(reason: str, next_action: str) -> bool:
    """Derive escalation from controlled policy, including exhausted invalid verdicts."""
    return reason in HUMAN_ACTION_REASONS or (
        reason in {"invalid_verdict", "legacy_verdict_identity"}
        and next_action == "operator_controller_action"
    )


NEXT_ACTIONS = frozenset(
    {
        "continue",
        "dispatch_replacement_verifier",
        "dispatch_remediation",
        "dispatch_read_only_diagnostician",
        "dispatch_repair",
        "dispatch_fresh_verifier",
        "serial_integration",
        "operator_controller_action",
        "provide_external_input",
        "authorize_scope",
        "inspect_adapter",
    }
)
HUMAN_ACTION_REASONS = frozenset(
    {
        "external_input",
        "external_authority",
        "safety_refusal",
        "scope_refusal",
        "budget_exhausted",
        "adapter_failure",
        "dispatch_failure",
        "unchanged_head",
        "remediation_failure",
        "fresh_verifier_failure",
        "contradictory_duplicate",
        "unknown_recovery_source",
        "ambiguous_blocker",
        "actor_unavailable",
        "repair_rejected",
        "repair_exhausted",
    }
)


class FeedbackValidationError(ValueError):
    """A packet, verdict, event, or admission request failed closed."""


class RecoverySource(str, Enum):
    VERIFIER_FAILURE = "verifier_failure"
    IMPLEMENTER_BLOCKED = "implementer_blocked"


class FeedbackPhase(str, Enum):
    AWAITING_VERDICT = "awaiting_verdict"
    AWAITING_REPLACEMENT_VERDICT = "awaiting_replacement_verdict"
    PACKET_ADMITTED = "packet_admitted"
    REMEDIATION_DISPATCHING = "remediation_dispatching"
    REMEDIATION_RUNNING = "remediation_running"
    AWAITING_FRESH_SURFACE = "awaiting_fresh_surface"
    AWAITING_FRESH_VERDICT = "awaiting_fresh_verdict"
    DIAGNOSTICIAN_DISPATCHING = "diagnostician_dispatching"
    DIAGNOSTICIAN_RUNNING = "diagnostician_running"
    REPAIR_SELECTION = "repair_selection"
    REPAIR_DISPATCHING = "repair_dispatching"
    REPAIR_RUNNING = "repair_running"
    READY_FOR_INTEGRATION = "ready_for_integration"
    TERMINAL_DONE = "terminal_done"
    TERMINAL_BLOCKED = "terminal_blocked"


@dataclass(frozen=True)
class EvidenceReference:
    path: str
    sha256: str


@dataclass(frozen=True)
class RemediationFeedback:
    schema_version: int
    packet_type: str
    identity_schema_version: str
    run_id: str
    spec_id: str
    implementation_head_digest: str
    verifier_head_commit: str
    containment_binding_digest: str
    source_verdict_digest: str
    failed_ac_ids: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]
    reproduction_commands: tuple[tuple[str, ...], ...]
    verification_commands: tuple[tuple[str, ...], ...]
    allowed_change_surface: tuple[str, ...]
    forbidden_surface: tuple[str, ...]
    guardrails: tuple[str, ...]
    causal_confidence: str
    remediation_ordinal: int
    signature: str

    def record(self) -> dict[str, Any]:
        value = asdict(self)
        value["failed_ac_ids"] = list(self.failed_ac_ids)
        value["evidence"] = [asdict(item) for item in self.evidence]
        for key in ("reproduction_commands", "verification_commands"):
            value[key] = [list(command) for command in getattr(self, key)]
        for key in ("allowed_change_surface", "forbidden_surface", "guardrails"):
            value[key] = list(getattr(self, key))
        return value


@dataclass(frozen=True)
class RecoveryAdmission:
    source: RecoverySource | None
    packet: RemediationFeedback | BlockedAttemptDiagnosis | None
    admitted: bool
    reason: str
    assessment: BlockedAttemptAssessment | None = None


def verifier_failure_resilience(
    packet: RemediationFeedback, verdict: Mapping[str, Any], *, max_rounds: int = 2,
) -> ResilienceDecision:
    """Derive the only permitted second verifier-failure remediation decision.

    The original packet's failed AC ids are immutable.  A later verdict earns
    round two only when its failed set is a strict subset; no prose or polling
    can renew that keyed effect.
    """
    current = tuple(
        str(item.get("id")) for item in verdict.get("acs", ())
        if isinstance(item, Mapping) and item.get("status") == "fail"
    )
    return decide_verifier_fail(packet.failed_ac_ids, current, max_rounds=max_rounds)


@dataclass(frozen=True)
class NormalizedFeedbackEvent:
    key: str
    kind: str
    role: str
    outcome: str
    source: str | None = None
    head: str | None = None
    applied_revision: str | None = None
    actor_id: str | None = None
    verdict: Mapping[str, Any] | None = None
    remediation_mode: str | None = None
    repair_route: str | None = None
    diagnosis_facts: tuple[str, ...] = ()
    candidate_refs: tuple[EvidenceReference, ...] = ()
    changed_paths: tuple[str, ...] = ()
    duration_s: float = 0.0
    reason: str = "ordinary_progress"
    next_action: str = "continue"

    def digest(self) -> str:
        return _digest(_json_safe(asdict(self)))


@dataclass(frozen=True)
class FeedbackEffect:
    key: str
    kind: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class FeedbackState:
    run_id: str
    spec_id: str
    implementation_head_digest: str
    expected_ac_ids: tuple[str, ...]
    original_authority: tuple[str, ...]
    candidate_branch: str = ""
    candidate_worktree_ref: str = ""
    implementer_ids: tuple[str, ...] = ()
    candidate_revision: str = ""
    verifier_head_commit: str = ""
    containment_binding_digest: str = ""
    controller_action_id: str | None = None
    prior_head_digest: str | None = None
    prior_verdict_digest: str | None = None
    phase: FeedbackPhase = FeedbackPhase.AWAITING_VERDICT
    packet: RemediationFeedback | None = None
    blocked_attempt: BlockedAttemptDiagnosis | None = None
    assessment: BlockedAttemptAssessment | None = None
    repair_selection: RepairSelection | None = None
    recovery_source: str | None = None
    diagnostician_used: int = 0
    diagnostician_limit: int = 1
    repair_used: int = 0
    repair_limit: int = 1
    repair_route: str | None = None
    diagnostician_id: str | None = None
    repairer_id: str | None = None
    remediation_mode: str | None = None
    remediation_used: int = 0
    remediation_limit: int = 2
    replacement_verifier_used: int = 0
    initial_verifier_id: str | None = None
    remediator_id: str | None = None
    remediated_implementation_head_digest: str | None = None
    remediated_candidate_revision: str | None = None
    remediated_verifier_head_commit: str | None = None
    remediated_containment_binding_digest: str | None = None
    processed_events: tuple[tuple[str, str], ...] = ()
    pending_effects: tuple[FeedbackEffect, ...] = ()
    delivered_effect_keys: tuple[str, ...] = ()
    failed_effect_keys: tuple[str, ...] = ()
    quarantined_event_keys: tuple[str, ...] = ()
    human_action_required: bool = False
    terminal_reason: str | None = None


class FeedbackRuntimeAdapter(Protocol):
    """Harness-neutral persistence, polling, and keyed-effect boundary."""

    def load_state(self, run_id: str) -> FeedbackState | None: ...
    def save_state(self, state: FeedbackState) -> None: ...
    def poll_events(self, run_id: str) -> Iterable[NormalizedFeedbackEvent]: ...
    def execute_effect(
        self, effect: FeedbackEffect, *, idempotency_key: str
    ) -> NormalizedFeedbackEvent | None: ...

    def load_integration_receipt(
        self, idempotency_key: str
    ) -> Mapping[str, Any] | None: ...

    def compare_and_set_integration_receipt(
        self,
        idempotency_key: str,
        *,
        expected_phase: str | None,
        receipt: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


KNOWN_EVENT_KINDS = frozenset({
    "actor_result",
    "verdict",
    "select_remediation",
    "remediation_dispatched",
    "remediation_result",
    "dispatch_failed",
    "integration_result",
    "recovery_admission",
    "diagnostician_dispatched",
    "diagnostician_result",
    "select_repair",
    "repair_dispatched",
    "repair_result",
})

# The complete persistence/effect boundary inventory owned by this reducer.  Tests
# consume this declaration mechanically so a new phase cannot be mistaken for a
# representative mid-flow sample.
OWNED_REPLAY_BOUNDARIES = (
    ("packet_persist", FeedbackPhase.PACKET_ADMITTED, "persist_packet"),
    ("remediation_dispatch", FeedbackPhase.REMEDIATION_DISPATCHING, "dispatch_remediation"),
    ("remediation_dispatch_result", FeedbackPhase.REMEDIATION_RUNNING, None),
    ("remediation_result", FeedbackPhase.AWAITING_FRESH_VERDICT, "dispatch_verifier"),
    ("integration_enqueue", FeedbackPhase.READY_FOR_INTEGRATION, "enqueue_integration_broker"),
    ("terminal_result", FeedbackPhase.TERMINAL_DONE, "terminal_resolution"),
)

IMPLEMENTER_RECOVERY_REPLAY_BOUNDARIES = (
    ("assessment_persist", FeedbackPhase.REPAIR_SELECTION, "persist_blocked_diagnosis"),
    ("repair_dispatch", FeedbackPhase.REPAIR_DISPATCHING, "dispatch_repair"),
    ("repair_dispatch_result", FeedbackPhase.REPAIR_RUNNING, None),
    ("repair_result", FeedbackPhase.AWAITING_FRESH_VERDICT, "dispatch_verifier"),
    ("independent_check", FeedbackPhase.READY_FOR_INTEGRATION, "enqueue_integration_broker"),
    ("application_result", FeedbackPhase.TERMINAL_DONE, "terminal_resolution"),
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        _json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _packet_unsigned(packet: RemediationFeedback) -> dict[str, Any]:
    value = packet.record()
    value.pop("signature")
    return value


def _validate_identity(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not IDENTITY_RE.fullmatch(value)
        or FORBIDDEN_TEXT_RE.search(value)
    ):
        raise FeedbackValidationError(f"invalid {label}")


def _validate_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise FeedbackValidationError(f"invalid {label}")


def _validate_safe_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN_LENGTH:
        raise FeedbackValidationError(f"invalid {label}")
    if FORBIDDEN_TEXT_RE.search(value):
        raise FeedbackValidationError(f"unsafe {label}")


def _validate_relative_path(value: str, label: str) -> None:
    _validate_safe_text(value, label)
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or value == ".git"
        or value.startswith(("~", ".git/"))
        or any(part.casefold() in PRIVATE_PATH_PARTS for part in path.parts)
    ):
        raise FeedbackValidationError(f"unsafe {label}")


def _within_surface(path: str, surface: str) -> bool:
    """Return whether a validated path is equal to or below a surface entry."""
    normalized = surface.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def validate_changed_surface(
    packet: RemediationFeedback, changed_paths: Iterable[str]
) -> None:
    """Reject a remediation result that escapes its exact parent-owned authority."""
    changed = tuple(changed_paths)
    if not changed or len(changed) > MAX_ITEMS or len(changed) != len(set(changed)):
        raise FeedbackValidationError("invalid changed surface")
    for path in changed:
        _validate_relative_path(path, "changed path")
        if not any(
            _within_surface(path, item) for item in packet.allowed_change_surface
        ):
            raise FeedbackValidationError("changed path exceeds allowed surface")
        if any(_within_surface(path, item) for item in packet.forbidden_surface):
            raise FeedbackValidationError("changed path enters forbidden surface")


def validate_evidence_content(packet: RemediationFeedback, project_root: Path) -> None:
    """Resolve relative evidence inside the project and reject stale content hashes."""
    root = project_root.resolve()
    for item in packet.evidence:
        _validate_relative_path(item.path, "evidence path")
        candidate = (root / item.path).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise FeedbackValidationError("evidence path is missing or outside project")
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual, item.sha256):
            raise FeedbackValidationError("stale evidence hash")


def _validate_command(command: tuple[str, ...], label: str) -> None:
    if not command or len(command) > MAX_ITEMS:
        raise FeedbackValidationError(f"invalid {label}")
    for token in command:
        _validate_safe_text(token, label)
        if any(mark in token for mark in (";", "&&", "||", ">", "<", "|")):
            raise FeedbackValidationError(f"shell interpolation in {label}")


def sign_payload(payload: Mapping[str, Any], parent_key: bytes) -> str:
    if not isinstance(parent_key, bytes) or len(parent_key) < 16:
        raise FeedbackValidationError("parent signing key is too short")
    return hmac.new(parent_key, _canonical_bytes(payload), hashlib.sha256).hexdigest()


def validate_remediation_feedback(
    packet: RemediationFeedback,
    *,
    parent_key: bytes,
    known_ac_ids: Iterable[str],
) -> None:
    if (
        packet.schema_version != PACKET_SCHEMA_VERSION
        or packet.packet_type != "remediation_feedback"
    ):
        raise FeedbackValidationError("unknown remediation packet schema")
    _validate_identity(packet.run_id, "run_id")
    _validate_identity(packet.spec_id, "spec_id")
    if packet.identity_schema_version != VERIFIER_IDENTITY_SCHEMA_VERSION:
        raise FeedbackValidationError("unknown verifier identity schema")
    _validate_hash(packet.implementation_head_digest, "implementation_head_digest")
    if not GIT_OBJECT_ID_RE.fullmatch(packet.verifier_head_commit):
        raise FeedbackValidationError("invalid verifier_head_commit")
    _validate_hash(packet.containment_binding_digest, "containment_binding_digest")
    _validate_hash(packet.source_verdict_digest, "source_verdict_digest")
    if packet.causal_confidence not in CAUSAL_CONFIDENCE:
        raise FeedbackValidationError("unknown causal confidence")
    if packet.remediation_ordinal != 1:
        raise FeedbackValidationError("remediation ordinal must be one")
    known = set(known_ac_ids)
    if not packet.failed_ac_ids or len(packet.failed_ac_ids) != len(
        set(packet.failed_ac_ids)
    ):
        raise FeedbackValidationError("failed AC IDs must be non-empty and unique")
    if any(
        not AC_RE.fullmatch(item) or item not in known for item in packet.failed_ac_ids
    ):
        raise FeedbackValidationError("unknown failed AC ID")
    if not packet.evidence or len(packet.evidence) > MAX_ITEMS:
        raise FeedbackValidationError("invalid evidence references")
    for item in packet.evidence:
        _validate_relative_path(item.path, "evidence path")
        _validate_hash(item.sha256, "evidence hash")
    for label, commands in (
        ("reproduction command", packet.reproduction_commands),
        ("verification command", packet.verification_commands),
    ):
        if not commands or len(commands) > MAX_ITEMS:
            raise FeedbackValidationError(f"invalid {label} vectors")
        for command in commands:
            _validate_command(command, label)
    for label, values in (
        ("allowed surface", packet.allowed_change_surface),
        ("forbidden surface", packet.forbidden_surface),
    ):
        if not values or len(values) > MAX_ITEMS or len(values) != len(set(values)):
            raise FeedbackValidationError(f"invalid {label}")
        for value in values:
            _validate_relative_path(value, label)
    if any(
        _within_surface(allowed, forbidden) or _within_surface(forbidden, allowed)
        for allowed in packet.allowed_change_surface
        for forbidden in packet.forbidden_surface
    ):
        raise FeedbackValidationError("allowed and forbidden surfaces overlap")
    if not packet.guardrails or len(packet.guardrails) > MAX_ITEMS:
        raise FeedbackValidationError("invalid guardrails")
    for guardrail in packet.guardrails:
        _validate_safe_text(guardrail, "guardrail")
    expected = sign_payload(_packet_unsigned(packet), parent_key)
    if not hmac.compare_digest(packet.signature, expected):
        raise FeedbackValidationError("invalid packet signature")
    record = packet.record()
    if set(record) & FORBIDDEN_PACKET_KEYS:
        raise FeedbackValidationError("forbidden packet field")
    if len(_canonical_bytes(record)) > MAX_PACKET_BYTES:
        raise FeedbackValidationError("remediation packet is oversized")


def remediation_feedback_from_dict(data: Mapping[str, Any]) -> RemediationFeedback:
    """Parse the closed packet schema; unknown and missing fields fail closed."""
    expected = set(RemediationFeedback.__dataclass_fields__)
    unknown = set(data) - expected
    missing = expected - set(data)
    if unknown or missing:
        raise FeedbackValidationError(
            f"packet fields mismatch (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    if set(data) & FORBIDDEN_PACKET_KEYS:
        raise FeedbackValidationError("forbidden packet field")
    try:
        return RemediationFeedback(
            schema_version=data["schema_version"],
            packet_type=data["packet_type"],
            identity_schema_version=data["identity_schema_version"],
            run_id=data["run_id"],
            spec_id=data["spec_id"],
            implementation_head_digest=data["implementation_head_digest"],
            verifier_head_commit=data["verifier_head_commit"],
            containment_binding_digest=data["containment_binding_digest"],
            source_verdict_digest=data["source_verdict_digest"],
            failed_ac_ids=tuple(data["failed_ac_ids"]),
            evidence=tuple(EvidenceReference(**item) for item in data["evidence"]),
            reproduction_commands=tuple(
                tuple(item) for item in data["reproduction_commands"]
            ),
            verification_commands=tuple(
                tuple(item) for item in data["verification_commands"]
            ),
            allowed_change_surface=tuple(data["allowed_change_surface"]),
            forbidden_surface=tuple(data["forbidden_surface"]),
            guardrails=tuple(data["guardrails"]),
            causal_confidence=data["causal_confidence"],
            remediation_ordinal=data["remediation_ordinal"],
            signature=data["signature"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FeedbackValidationError("invalid packet field types") from exc


def feedback_state_record(state: FeedbackState) -> dict[str, Any]:
    """Serialize every durable reducer field without losing controller provenance."""
    return _json_safe(asdict(state))


def feedback_state_from_dict(data: Mapping[str, Any]) -> FeedbackState:
    """Restore a closed durable state record produced by :func:`feedback_state_record`."""
    expected = set(FeedbackState.__dataclass_fields__)
    convergence_fields = {
        "blocked_attempt", "assessment", "repair_selection", "recovery_source",
        "diagnostician_used", "diagnostician_limit", "repair_used", "repair_limit",
        "repair_route", "diagnostician_id", "repairer_id",
    }
    if frozenset(data) not in {frozenset(expected), frozenset(expected - convergence_fields)}:
        raise FeedbackValidationError("feedback state fields mismatch")
    data = {
        **{
            "blocked_attempt": None,
            "assessment": None,
            "repair_selection": None,
            "recovery_source": None,
            "diagnostician_used": 0,
            "diagnostician_limit": 1,
            "repair_used": 0,
            "repair_limit": 1,
            "repair_route": None,
            "diagnostician_id": None,
            "repairer_id": None,
        },
        **dict(data),
    }
    try:
        packet_data = data.get("packet")
        blocked_data = data.get("blocked_attempt")
        blocked_attempt = None
        assessment = None
        if blocked_data is not None:
            blocked_attempt = blocked_attempt_from_dict(
                blocked_data,
                run_id=data["run_id"],
                spec_id=data["spec_id"],
                candidate_revision=data["candidate_revision"],
                implementation_head_digest=data["implementation_head_digest"],
                known_ac_ids=data["expected_ac_ids"],
                changed_paths=[item["path"] for item in blocked_data["partial_work"]],
            )
            assessment = assess_blocked_attempt(blocked_attempt)
            if data.get("assessment") != assessment.record():
                raise FeedbackValidationError("assessment does not match blocked evidence")
        selection_data = data.get("repair_selection")
        repair_selection = None
        if selection_data is not None:
            if assessment is None:
                raise FeedbackValidationError("repair selection lacks assessment")
            repair_selection = select_repair_route(
                assessment,
                route=RepairRoute(selection_data["route"]).value,
                files=selection_data["files"],
                ac_ids=selection_data["ac_ids"],
                capability=selection_data["capability"],
                active_surfaces=(),
            )
            if [list(item) for item in repair_selection.probes] != selection_data["probes"]:
                raise FeedbackValidationError("repair selection probes do not match assessment")
        effects = tuple(
            FeedbackEffect(
                key=item["key"], kind=item["kind"], payload=dict(item["payload"])
            )
            for item in data["pending_effects"]
        )
        state = FeedbackState(
            run_id=data["run_id"],
            spec_id=data["spec_id"],
            implementation_head_digest=data["implementation_head_digest"],
            expected_ac_ids=tuple(data["expected_ac_ids"]),
            original_authority=tuple(data["original_authority"]),
            candidate_branch=data["candidate_branch"],
            candidate_worktree_ref=data["candidate_worktree_ref"],
            implementer_ids=tuple(data["implementer_ids"]),
            candidate_revision=data["candidate_revision"],
            verifier_head_commit=data["verifier_head_commit"],
            containment_binding_digest=data["containment_binding_digest"],
            controller_action_id=data["controller_action_id"],
            prior_head_digest=data["prior_head_digest"],
            prior_verdict_digest=data["prior_verdict_digest"],
            phase=FeedbackPhase(data["phase"]),
            packet=(
                remediation_feedback_from_dict(packet_data)
                if packet_data is not None
                else None
            ),
            blocked_attempt=blocked_attempt,
            assessment=assessment,
            repair_selection=repair_selection,
            recovery_source=data["recovery_source"],
            diagnostician_used=data["diagnostician_used"],
            diagnostician_limit=data["diagnostician_limit"],
            repair_used=data["repair_used"],
            repair_limit=data["repair_limit"],
            repair_route=data["repair_route"],
            diagnostician_id=data["diagnostician_id"],
            repairer_id=data["repairer_id"],
            remediation_mode=data["remediation_mode"],
            remediation_used=data["remediation_used"],
            remediation_limit=data["remediation_limit"],
            replacement_verifier_used=data["replacement_verifier_used"],
            initial_verifier_id=data["initial_verifier_id"],
            remediator_id=data["remediator_id"],
            remediated_implementation_head_digest=data["remediated_implementation_head_digest"],
            remediated_candidate_revision=data["remediated_candidate_revision"],
            remediated_verifier_head_commit=data["remediated_verifier_head_commit"],
            remediated_containment_binding_digest=data["remediated_containment_binding_digest"],
            processed_events=tuple(tuple(item) for item in data["processed_events"]),
            pending_effects=effects,
            delivered_effect_keys=tuple(data["delivered_effect_keys"]),
            failed_effect_keys=tuple(data["failed_effect_keys"]),
            quarantined_event_keys=tuple(data["quarantined_event_keys"]),
            human_action_required=data["human_action_required"],
            terminal_reason=data["terminal_reason"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FeedbackValidationError("invalid feedback state field types") from exc
    _validate_identity(state.run_id, "run id")
    _validate_identity(state.spec_id, "spec id")
    _validate_hash(state.implementation_head_digest, "implementation head")
    if state.candidate_revision and not GIT_OBJECT_ID_RE.fullmatch(state.candidate_revision):
        raise FeedbackValidationError("invalid candidate revision")
    if state.verifier_head_commit and not GIT_OBJECT_ID_RE.fullmatch(state.verifier_head_commit):
        raise FeedbackValidationError("invalid verifier head commit")
    if state.containment_binding_digest:
        _validate_hash(state.containment_binding_digest, "containment binding digest")
    if state.controller_action_id is not None:
        _validate_identity(state.controller_action_id, "controller action id")
    for label, value in (
        ("prior head digest", state.prior_head_digest),
        ("prior verdict digest", state.prior_verdict_digest),
    ):
        if value is not None:
            _validate_hash(value, label)
    if not (
        0 <= state.diagnostician_used <= state.diagnostician_limit == 1
        and 0 <= state.repair_used <= state.repair_limit == 1
    ):
        raise FeedbackValidationError("implementer recovery allowance is invalid")
    return state


def _verdict_digest(verdict: Mapping[str, Any]) -> str:
    return _digest(dict(verdict))


def validate_verifier_verdict(
    verdict: Mapping[str, Any],
    *,
    spec_id: str,
    implementation_head_digest: str,
    verifier_head_commit: str,
    expected_ac_ids: Iterable[str],
    verifier_id: str,
    implementer_ids: Iterable[str] = (),
) -> None:
    errors = validate_verifier_verdict_dict(dict(verdict))
    if errors:
        raise FeedbackValidationError("invalid verifier schema: " + "; ".join(errors))
    if "implementation_head_digest" not in verdict:
        raise FeedbackValidationError("legacy_verdict_missing_implementation_head_digest")
    if (
        verdict.get("spec_id") != spec_id
        or verdict.get("head_commit") != verifier_head_commit
        or verdict.get("implementation_head_digest") != implementation_head_digest
        or verdict.get("identity_schema_version") != VERIFIER_IDENTITY_SCHEMA_VERSION
    ):
        raise FeedbackValidationError("stale or mismatched verdict identity")
    if verdict.get("contamination") is not None:
        raise FeedbackValidationError("contaminated verdict")
    if not verifier_id or verifier_id in set(implementer_ids):
        raise FeedbackValidationError("verifier is not independent")
    footprint = verdict.get("git_footprint")
    if (
        not isinstance(footprint, Mapping)
        or footprint.get("tree_before") != footprint.get("tree_after")
        or footprint.get("porcelain")
    ):
        raise FeedbackValidationError("verifier write footprint is not clean")
    acs = verdict.get("acs")
    if not isinstance(acs, list) or not acs:
        raise FeedbackValidationError("verdict has no AC evidence")
    expected = tuple(expected_ac_ids)
    reported: list[str] = []
    for item in acs:
        if not isinstance(item, Mapping) or item.get("status") not in {
            "pass",
            "fail",
            "unverifiable",
        }:
            raise FeedbackValidationError("invalid per-AC result")
        if not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise FeedbackValidationError("missing per-AC evidence")
        reported.append(item.get("id"))
    if len(reported) != len(set(reported)) or set(reported) != set(expected):
        raise FeedbackValidationError("incomplete or duplicate AC coverage")


def validate_failure_verdict(
    verdict: Mapping[str, Any],
    *,
    spec_id: str,
    implementation_head_digest: str,
    verifier_head_commit: str,
    expected_ac_ids: Iterable[str],
    verifier_id: str,
    implementer_ids: Iterable[str] = (),
) -> tuple[str, ...]:
    validate_verifier_verdict(
        verdict,
        spec_id=spec_id,
        implementation_head_digest=implementation_head_digest,
        verifier_head_commit=verifier_head_commit,
        expected_ac_ids=expected_ac_ids,
        verifier_id=verifier_id,
        implementer_ids=implementer_ids,
    )
    if verdict.get("verdict") != "fail":
        raise FeedbackValidationError("verdict is not a failure")
    acs = verdict.get("acs")
    expected = tuple(expected_ac_ids)
    failed = tuple(
        item.get("id")
        for item in acs
        if isinstance(item, Mapping) and item.get("status") == "fail"
    )
    if (
        not failed
        or len(failed) != len(set(failed))
        or any(item not in expected for item in failed)
    ):
        raise FeedbackValidationError("invalid failed AC evidence")
    return failed


def create_remediation_feedback(
    *,
    run_id: str,
    spec_id: str,
    implementation_head_digest: str,
    candidate_revision: str,
    dispatch_plan: Mapping[str, Any],
    containment_evidence: Mapping[str, Any],
    verdict: Mapping[str, Any],
    verifier_id: str,
    expected_ac_ids: Iterable[str],
    evidence: Iterable[EvidenceReference],
    reproduction_commands: Iterable[Iterable[str]],
    verification_commands: Iterable[Iterable[str]],
    allowed_change_surface: Iterable[str] | None,
    forbidden_surface: Iterable[str],
    guardrails: Iterable[str],
    causal_confidence: str,
    parent_key: bytes,
    project_root: Path,
    implementer_ids: Iterable[str] = (),
) -> RemediationFeedback:
    expected = tuple(expected_ac_ids)
    if "implementation_head_digest" not in verdict:
        raise FeedbackValidationError("legacy_verdict_identity")
    try:
        identity = validate_dispatch_identity(
            dispatch_plan=dict(dispatch_plan),
            containment_evidence=dict(containment_evidence),
            verdict=dict(verdict),
            spec_id=spec_id,
            run_id=run_id,
            candidate_revision=candidate_revision,
        )
    except ValueError as exc:
        raise FeedbackValidationError("verifier_identity_mismatch") from exc
    failed = validate_failure_verdict(
        verdict,
        spec_id=spec_id,
        implementation_head_digest=implementation_head_digest,
        verifier_head_commit=str(dispatch_plan.get("head_commit", "")),
        expected_ac_ids=expected,
        verifier_id=verifier_id,
        implementer_ids=implementer_ids,
    )
    declared_surface = verdict.get("allowed_change_surface")
    if (
        not isinstance(declared_surface, list)
        or not declared_surface
        or len(declared_surface) != len(set(declared_surface))
        or not all(isinstance(item, str) for item in declared_surface)
    ):
        raise FeedbackValidationError("failure verdict has no valid declared change surface")
    for item in declared_surface:
        _validate_relative_path(item, "verdict declared surface")
    if allowed_change_surface is not None and tuple(allowed_change_surface) != tuple(
        declared_surface
    ):
        raise FeedbackValidationError("caller surface differs from verdict declaration")
    unsigned = RemediationFeedback(
        schema_version=PACKET_SCHEMA_VERSION,
        packet_type="remediation_feedback",
        identity_schema_version=VERIFIER_IDENTITY_SCHEMA_VERSION,
        run_id=run_id,
        spec_id=spec_id,
        implementation_head_digest=implementation_head_digest,
        verifier_head_commit=str(dispatch_plan["head_commit"]),
        containment_binding_digest=identity["containment_binding_digest"],
        source_verdict_digest=_verdict_digest(verdict),
        failed_ac_ids=failed,
        evidence=tuple(evidence),
        reproduction_commands=tuple(
            tuple(command) for command in reproduction_commands
        ),
        verification_commands=tuple(
            tuple(command) for command in verification_commands
        ),
        allowed_change_surface=tuple(declared_surface),
        forbidden_surface=tuple(forbidden_surface),
        guardrails=tuple(guardrails),
        causal_confidence=causal_confidence,
        remediation_ordinal=1,
        signature="",
    )
    packet = replace(
        unsigned, signature=sign_payload(_packet_unsigned(unsigned), parent_key)
    )
    validate_remediation_feedback(packet, parent_key=parent_key, known_ac_ids=expected)
    validate_evidence_content(packet, project_root)
    return packet


def admit_recovery(
    source: str,
    *,
    packet: RemediationFeedback | None,
    blocked_attempt: BlockedAttemptDiagnosis | None = None,
    assessment: BlockedAttemptAssessment | None = None,
) -> RecoveryAdmission:
    """Admit either source through one typed, parent-owned recovery seam."""
    try:
        typed = RecoverySource(source)
    except ValueError:
        return RecoveryAdmission(None, None, False, "unknown_recovery_source")
    if typed is RecoverySource.VERIFIER_FAILURE and packet is not None:
        return RecoveryAdmission(typed, packet, True, "ordinary_progress")
    if typed is RecoverySource.IMPLEMENTER_BLOCKED:
        if blocked_attempt is not None and assessment is not None and assessment.eligible:
            return RecoveryAdmission(
                typed, blocked_attempt, True, "ordinary_progress", assessment
            )
        if assessment is not None:
            reason = {
                DiagnosisClass.EXTERNAL_INPUT: "external_input",
                DiagnosisClass.SAFETY_OR_SCOPE: "scope_refusal",
            }.get(assessment.classification, "ambiguous_blocker")
            return RecoveryAdmission(typed, blocked_attempt, False, reason, assessment)
        return RecoveryAdmission(typed, None, False, "implementer_blocked")
    return RecoveryAdmission(typed, None, False, "invalid_verdict")


def resume_controller_action(
    prior: FeedbackState,
    *,
    action_id: str,
    run_id: str,
    prior_head_digest: str,
    prior_verdict_digest: str,
) -> FeedbackState:
    """Start an explicit new controller action from a terminal attempt.

    Polling and reconnecting only reload ``prior``.  A budget is available again
    only through this parent-owned constructor, which binds the new action to
    the prior implementation head and admitted verdict digest.
    """
    _validate_identity(action_id, "controller action id")
    _validate_identity(run_id, "run id")
    _validate_hash(prior_head_digest, "prior head digest")
    _validate_hash(prior_verdict_digest, "prior verdict digest")
    if prior.phase not in {FeedbackPhase.TERMINAL_DONE, FeedbackPhase.TERMINAL_BLOCKED}:
        raise FeedbackValidationError("controller resume requires a terminal prior action")
    expected_verdict = (
        prior.packet.source_verdict_digest if prior.packet else "0" * 64
    )
    if prior_head_digest != prior.implementation_head_digest or prior_verdict_digest != expected_verdict:
        raise FeedbackValidationError("controller resume prior digest mismatch")
    return FeedbackState(
        run_id=run_id,
        spec_id=prior.spec_id,
        implementation_head_digest=prior.implementation_head_digest,
        expected_ac_ids=prior.expected_ac_ids,
        original_authority=prior.original_authority,
        candidate_branch=prior.candidate_branch,
        candidate_worktree_ref=prior.candidate_worktree_ref,
        implementer_ids=prior.implementer_ids,
        candidate_revision=prior.candidate_revision,
        verifier_head_commit=prior.verifier_head_commit,
        containment_binding_digest=prior.containment_binding_digest,
        controller_action_id=action_id,
        prior_head_digest=prior_head_digest,
        prior_verdict_digest=prior_verdict_digest,
    )


def surfaces_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    """Conservatively detect equal or ancestor-related repository surfaces."""
    left_paths = [PurePosixPath(item) for item in left]
    right_paths = [PurePosixPath(item) for item in right]
    for path in (*left_paths, *right_paths):
        _validate_relative_path(path.as_posix(), "overlap surface")
    return any(
        a == b or a in b.parents or b in a.parents
        for a in left_paths
        for b in right_paths
    )


def normalized_outcome_record(
    state: FeedbackState,
    event: NormalizedFeedbackEvent,
    *,
    terminal_outcome: str | None = None,
    human_action_required: bool | None = None,
) -> dict[str, Any]:
    if event.role not in ACTOR_ROLES or event.outcome not in ACTOR_OUTCOMES:
        raise FeedbackValidationError("invalid role or actor outcome")
    if event.reason not in CONTROLLED_REASONS or event.next_action not in NEXT_ACTIONS:
        raise FeedbackValidationError("invalid outcome reason or next action")
    if event.duration_s < 0:
        raise FeedbackValidationError("duration must be non-negative")
    if event.head is not None:
        _validate_hash(event.head, "outcome head")
    derived_human_action = _human_action_for(event.reason, event.next_action)
    if (
        human_action_required is not None
        and human_action_required is not derived_human_action
    ):
        raise FeedbackValidationError(
            "human action is inconsistent with the controlled reason policy"
        )
    refs = [{"path": item.path, "sha256": item.sha256} for item in event.candidate_refs]
    for item in event.candidate_refs:
        _validate_relative_path(item.path, "candidate reference")
        _validate_hash(item.sha256, "candidate hash")
    return {
        "schema_version": 1,
        "spec_id": state.spec_id,
        "run_id": state.run_id,
        "role": event.role,
        "agent_outcome": event.outcome,
        "reason": event.reason,
        "head_digest": event.head,
        "artifact_refs": refs,
        "idempotency_key": event.key,
        "attempt_ordinal": 1,
        "duration_s": event.duration_s,
        "terminal_outcome": terminal_outcome,
        "human_action_required": derived_human_action,
        "next_action": event.next_action,
        "recovery_source": state.recovery_source,
        "diagnosis_class": (
            state.assessment.classification.value if state.assessment else None
        ),
        "causal_confidence": state.assessment.confidence if state.assessment else None,
        "candidate_preserved": bool(
            state.candidate_branch or state.candidate_worktree_ref or state.blocked_attempt
        ),
        "repair_route": state.repair_route,
        "diagnostician_allowance": {
            "used": state.diagnostician_used,
            "limit": state.diagnostician_limit,
        },
        "repair_allowance": {
            "used": state.repair_used,
            "limit": state.repair_limit,
        },
        "operator_action": event.next_action if derived_human_action else None,
        "delivery_phase": state.phase.value,
    }


def _effect(
    state: FeedbackState, kind: str, suffix: str, **payload: Any
) -> FeedbackEffect:
    verdict_digest = (
        state.packet.source_verdict_digest if state.packet else "no-verdict"
    )
    assessment_digest = state.assessment.digest() if state.assessment else "no-assessment"
    recovery_identity = ":".join((
        state.recovery_source or "verifier_failure",
        assessment_digest,
        state.candidate_revision or "no-candidate",
        state.repair_route or state.remediation_mode or "no-route",
        str(max(state.repair_used, state.remediation_used, 0)),
    ))
    key = (
        f"feedback:{state.run_id}:{state.spec_id}:{state.implementation_head_digest}:"
        f"{verdict_digest}:{recovery_identity}:{suffix}"
    )
    return FeedbackEffect(key=key, kind=kind, payload=_json_safe(payload))


def _append_effects(state: FeedbackState, *effects: FeedbackEffect) -> FeedbackState:
    existing = {item.key for item in state.pending_effects} | set(
        state.delivered_effect_keys
    )
    return replace(
        state,
        pending_effects=state.pending_effects
        + tuple(item for item in effects if item.key not in existing),
    )


def _terminal(
    state: FeedbackState, reason: str, *, human: bool, event: NormalizedFeedbackEvent
) -> FeedbackState:
    derived_human_action = _human_action_for(reason, event.next_action)
    if human is not derived_human_action:
        raise FeedbackValidationError(
            "terminal human action is inconsistent with the controlled reason policy"
        )
    state = replace(
        state,
        phase=FeedbackPhase.TERMINAL_BLOCKED,
        terminal_reason=reason,
        human_action_required=derived_human_action,
    )
    return _append_effects(
        state,
        _effect(
            state,
            "record_outcome",
            f"outcome:{event.key}",
            record=normalized_outcome_record(
                state,
                event,
                terminal_outcome="blocked",
                human_action_required=derived_human_action,
            ),
        ),
        _effect(
            state,
            "terminal_resolution",
            "terminal:blocked",
            outcome="blocked",
            reason=reason,
            human_action_required=derived_human_action,
            remediation_budget={
                "used": state.remediation_used,
                "limit": state.remediation_limit,
            },
            diagnostician_allowance={
                "used": state.diagnostician_used,
                "limit": state.diagnostician_limit,
            },
            repair_allowance={
                "used": state.repair_used,
                "limit": state.repair_limit,
            },
            assessment=(state.assessment.record() if state.assessment else None),
            repair_route=state.repair_route,
            preserved_candidate={
                "branch": state.candidate_branch,
                "worktree_ref": state.candidate_worktree_ref,
                "evidence": [
                    asdict(item) for item in (state.packet.evidence if state.packet else ())
                ],
            },
        ),
    )


def _event_expected(state: FeedbackState, event: NormalizedFeedbackEvent) -> bool:
    """Leave early delivery unconsumed so durable polling can replay it later."""
    active = set(FeedbackPhase) - {
        FeedbackPhase.TERMINAL_DONE,
        FeedbackPhase.TERMINAL_BLOCKED,
    }
    allowed = {
        "actor_result": active,
        "verdict": {
            FeedbackPhase.AWAITING_VERDICT,
            FeedbackPhase.AWAITING_REPLACEMENT_VERDICT,
            FeedbackPhase.AWAITING_FRESH_VERDICT,
        },
        "select_remediation": {FeedbackPhase.PACKET_ADMITTED},
        "remediation_dispatched": {FeedbackPhase.REMEDIATION_DISPATCHING},
        "remediation_result": {
            FeedbackPhase.REMEDIATION_DISPATCHING,
            FeedbackPhase.REMEDIATION_RUNNING,
        },
        "dispatch_failed": active,
        "integration_result": {FeedbackPhase.READY_FOR_INTEGRATION},
        "recovery_admission": active,
        "diagnostician_dispatched": {FeedbackPhase.DIAGNOSTICIAN_DISPATCHING},
        "diagnostician_result": {
            FeedbackPhase.DIAGNOSTICIAN_DISPATCHING,
            FeedbackPhase.DIAGNOSTICIAN_RUNNING,
        },
        "select_repair": {FeedbackPhase.REPAIR_SELECTION},
        "repair_dispatched": {FeedbackPhase.REPAIR_DISPATCHING},
        "repair_result": {
            FeedbackPhase.REPAIR_DISPATCHING,
            FeedbackPhase.REPAIR_RUNNING,
        },
    }
    return state.phase in allowed.get(event.kind, set())


def _record_actor_effect(
    state: FeedbackState, event: NormalizedFeedbackEvent
) -> FeedbackState:
    return _append_effects(
        state,
        _effect(
            state,
            "record_outcome",
            f"actor-outcome:{event.key}",
            record=normalized_outcome_record(state, event),
        ),
    )


def _assessment_terminal(
    state: FeedbackState,
    event: NormalizedFeedbackEvent,
    assessment: BlockedAttemptAssessment,
) -> FeedbackState:
    if assessment.classification is DiagnosisClass.EXTERNAL_INPUT:
        reason, next_action = "external_input", "provide_external_input"
    elif assessment.classification is DiagnosisClass.SAFETY_OR_SCOPE:
        reason, next_action = "scope_refusal", "authorize_scope"
    else:
        reason, next_action = "ambiguous_blocker", "operator_controller_action"
    return _terminal(
        state,
        reason,
        human=True,
        event=replace(
            event,
            role="parent",
            outcome="blocked",
            reason=reason,
            next_action=next_action,
        ),
    )


def _open_blocked_assessment(
    state: FeedbackState,
    event: NormalizedFeedbackEvent,
    *,
    packet_inputs: Mapping[str, Any] | None,
) -> FeedbackState:
    """Preserve and classify an attempt without turning actor status into lifecycle."""
    raw = packet_inputs.get("blocked_attempt_diagnosis") if packet_inputs else None
    try:
        if not state.candidate_branch or not state.candidate_worktree_ref:
            raise RecoveryConvergenceError("candidate preservation identity is missing")
        _validate_safe_text(state.candidate_branch, "candidate branch")
        _validate_relative_path(state.candidate_worktree_ref, "candidate worktree reference")
        packet = blocked_attempt_from_dict(
            raw,
            run_id=state.run_id,
            spec_id=state.spec_id,
            candidate_revision=state.candidate_revision,
            implementation_head_digest=state.implementation_head_digest,
            known_ac_ids=state.expected_ac_ids,
            changed_paths=event.changed_paths,
        )
        assessment = assess_blocked_attempt(packet)
        admission = admit_recovery(
            RecoverySource.IMPLEMENTER_BLOCKED.value,
            packet=None,
            blocked_attempt=packet,
            assessment=assessment,
        )
    except (RecoveryConvergenceError, TypeError):
        failed = replace(state, recovery_source=RecoverySource.IMPLEMENTER_BLOCKED.value)
        return _terminal(
            failed,
            "ambiguous_blocker",
            human=True,
            event=replace(
                event,
                role="parent",
                outcome="blocked",
                reason="ambiguous_blocker",
                next_action="operator_controller_action",
            ),
        )
    assessed = replace(
        state,
        blocked_attempt=packet,
        assessment=assessment,
        recovery_source=RecoverySource.IMPLEMENTER_BLOCKED.value,
    )
    assessed = _append_effects(
        assessed,
        _effect(
            assessed,
            "preserve_candidate",
            "preserve-candidate",
            branch=state.candidate_branch,
            worktree_ref=state.candidate_worktree_ref,
            candidate_revision=state.candidate_revision,
            partial_work=[asdict(item) for item in packet.partial_work],
        ),
        _effect(
            assessed,
            "persist_blocked_diagnosis",
            "persist-diagnosis",
            diagnosis=packet.record(),
            assessment=assessment.record(),
        ),
    )
    if admission.admitted:
        return replace(assessed, phase=FeedbackPhase.REPAIR_SELECTION)
    if assessment.diagnostician_required and assessed.diagnostician_used == 0:
        dispatching = replace(
            assessed,
            phase=FeedbackPhase.DIAGNOSTICIAN_DISPATCHING,
            diagnostician_used=1,
        )
        return _append_effects(
            dispatching,
            _effect(
                dispatching,
                "dispatch_diagnostician",
                "diagnostician:1",
                read_only=True,
                ordinal=1,
                assessment=assessment.record(),
                allowed_files=list(assessment.next_task.files if assessment.next_task else ()),
                allowed_ac_ids=list(assessment.next_task.ac_ids if assessment.next_task else ()),
            ),
        )
    return _assessment_terminal(assessed, event, assessment)


def reduce_feedback_event(
    state: FeedbackState,
    event: NormalizedFeedbackEvent,
    *,
    parent_key: bytes,
    packet_inputs: Mapping[str, Any] | None = None,
) -> FeedbackState:
    _validate_identity(event.key, "event key")
    digest = event.digest()
    prior = dict(state.processed_events)
    if event.key in prior:
        if prior[event.key] == digest:
            return state
        quarantined = tuple(dict.fromkeys((*state.quarantined_event_keys, event.key)))
        failed = replace(state, quarantined_event_keys=quarantined)
        failed = _append_effects(
            failed,
            _effect(
                failed,
                "quarantine",
                f"quarantine:{event.key}",
                event_key=event.key,
                reason="contradictory_duplicate",
            ),
        )
        if state.phase in {
            FeedbackPhase.TERMINAL_DONE,
            FeedbackPhase.TERMINAL_BLOCKED,
        }:
            return failed
        return _terminal(
            failed,
            "contradictory_duplicate",
            human=True,
            event=replace(
                event,
                role="parent",
                outcome="blocked",
                reason="contradictory_duplicate",
                next_action="operator_controller_action",
            ),
        )
    if state.phase in {FeedbackPhase.TERMINAL_DONE, FeedbackPhase.TERMINAL_BLOCKED}:
        return state
    if event.kind not in KNOWN_EVENT_KINDS:
        rejected = replace(
            event,
            role="parent",
            outcome="blocked",
            reason="scope_refusal",
            next_action="authorize_scope",
        )
        return _terminal(state, "scope_refusal", human=True, event=rejected)
    if not _event_expected(state, event):
        return state
    state = replace(
        state, processed_events=state.processed_events + ((event.key, digest),)
    )

    if event.kind == "actor_result":
        state = _record_actor_effect(state, event)
        if _human_action_for(event.reason, event.next_action):
            return _terminal(
                state,
                event.reason,
                human=True,
                event=replace(event, role="parent", outcome="blocked"),
            )
        if attempt_requires_delivery_assessment(event.role, event.outcome):
            return _open_blocked_assessment(
                state, event, packet_inputs=packet_inputs
            )
        return state

    if event.kind == "diagnostician_dispatched":
        if event.role != "parent":
            return _assessment_terminal(
                state,
                event,
                state.assessment or assess_blocked_attempt(state.blocked_attempt),
            )
        return replace(state, phase=FeedbackPhase.DIAGNOSTICIAN_RUNNING)

    if event.kind == "diagnostician_result":
        state = _record_actor_effect(state, event)
        if (
            event.role != "diagnostician"
            or event.outcome != "completed"
            or not event.actor_id
            or not event.candidate_refs
            or state.blocked_attempt is None
            or state.diagnostician_used != 1
        ):
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="actor_unavailable", next_action="operator_controller_action",
            )
            return _terminal(state, "actor_unavailable", human=True, event=blocked)
        raw = state.blocked_attempt.record()
        raw["blocker_facts"] = list(event.diagnosis_facts)
        raw["artifact_refs"] = [
            *raw["artifact_refs"],
            *[asdict(item) for item in event.candidate_refs],
        ]
        packet = state.blocked_attempt
        try:
            packet = blocked_attempt_from_dict(
                raw,
                run_id=state.run_id,
                spec_id=state.spec_id,
                candidate_revision=state.candidate_revision,
                implementation_head_digest=state.implementation_head_digest,
                known_ac_ids=state.expected_ac_ids,
                changed_paths=tuple(item.path for item in state.blocked_attempt.partial_work),
            )
            assessment = assess_blocked_attempt(packet)
            admission = admit_recovery(
                RecoverySource.IMPLEMENTER_BLOCKED.value,
                packet=None,
                blocked_attempt=packet,
                assessment=assessment,
            )
        except RecoveryConvergenceError:
            assessment = state.assessment
            admission = RecoveryAdmission(
                RecoverySource.IMPLEMENTER_BLOCKED,
                state.blocked_attempt,
                False,
                "ambiguous_blocker",
                assessment,
            )
        diagnosed = replace(
            state,
            blocked_attempt=packet,
            assessment=assessment,
            diagnostician_id=event.actor_id,
        )
        if admission.admitted:
            return replace(diagnosed, phase=FeedbackPhase.REPAIR_SELECTION)
        return _assessment_terminal(diagnosed, event, assessment)

    if event.kind == "select_repair":
        if (
            event.role != "parent"
            or state.assessment is None
            or state.repair_used != 0
            or packet_inputs is None
            or not isinstance(packet_inputs.get("repair_selection"), Mapping)
        ):
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="repair_exhausted", next_action="operator_controller_action",
            )
            return _terminal(state, "repair_exhausted", human=True, event=blocked)
        raw_selection = packet_inputs["repair_selection"]
        try:
            selection = select_repair_route(
                state.assessment,
                route=event.repair_route or "",
                files=raw_selection.get("files", ()),
                ac_ids=raw_selection.get("ac_ids", ()),
                capability=raw_selection.get("capability", ""),
                active_surfaces=raw_selection.get("active_surfaces", ()),
            )
        except RecoveryConvergenceError:
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="scope_refusal", next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked)
        selected = replace(
            state,
            phase=FeedbackPhase.REPAIR_DISPATCHING,
            repair_selection=selection,
            repair_route=selection.route.value,
            repair_used=1,
        )
        return _append_effects(
            selected,
            _effect(
                selected,
                "dispatch_repair",
                "repair:1",
                route=selection.route.value,
                ordinal=1,
                files=list(selection.files),
                ac_ids=list(selection.ac_ids),
                capability=selection.capability,
                probes=[list(item) for item in selection.probes],
                candidate_revision=state.candidate_revision,
                lifecycle_authority=False,
                integration_authority=False,
                self_approval=False,
            ),
        )

    if event.kind == "repair_dispatched":
        if event.role != "parent":
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="scope_refusal", next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked)
        return replace(state, phase=FeedbackPhase.REPAIR_RUNNING)

    if event.kind == "repair_result":
        state = _record_actor_effect(state, event)
        fresh_candidate_revision = (
            packet_inputs.get("fresh_candidate_revision") if packet_inputs else None
        )
        fresh_dispatch_plan = packet_inputs.get("fresh_dispatch_plan") if packet_inputs else None
        fresh_containment_evidence = (
            packet_inputs.get("fresh_containment_evidence") if packet_inputs else None
        )
        expected_role = (
            "implementer" if state.repair_route == "resume_original" else "repairer"
        )
        actor_matches_route = (
            event.role == expected_role
            and bool(event.actor_id)
            and (
                event.actor_id in state.implementer_ids
                if expected_role == "implementer"
                else event.actor_id not in {
                    *state.implementer_ids,
                    state.diagnostician_id,
                }
            )
        )
        if not actor_matches_route:
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="repair_rejected", next_action="operator_controller_action",
            )
            return _terminal(state, "repair_rejected", human=True, event=blocked)
        if event.outcome != "completed":
            reason = "actor_unavailable" if event.outcome == "unavailable" else "repair_rejected"
            blocked = replace(
                event, role="parent", outcome="blocked", reason=reason,
                next_action="operator_controller_action",
            )
            return _terminal(state, reason, human=True, event=blocked)
        if (
            state.repair_selection is None
            or not event.head
            or not isinstance(fresh_candidate_revision, str)
            or not GIT_OBJECT_ID_RE.fullmatch(fresh_candidate_revision)
        ):
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="repair_rejected", next_action="operator_controller_action",
            )
            return _terminal(state, "repair_rejected", human=True, event=blocked)
        if fresh_candidate_revision == state.candidate_revision:
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="unchanged_head", next_action="operator_controller_action",
            )
            return _terminal(state, "unchanged_head", human=True, event=blocked)
        try:
            for path in event.changed_paths:
                _validate_relative_path(path, "repair changed path")
            changed = tuple(event.changed_paths)
            if not changed or not set(changed) <= set(state.repair_selection.files):
                raise FeedbackValidationError("repair changed undeclared files")
            if not isinstance(fresh_dispatch_plan, Mapping) or not isinstance(
                fresh_containment_evidence, Mapping
            ):
                raise FeedbackValidationError("fresh verifier surface is missing")
            identity = validate_dispatch_identity(
                dispatch_plan=dict(fresh_dispatch_plan),
                containment_evidence=dict(fresh_containment_evidence),
                verdict={
                    "identity_schema_version": VERIFIER_IDENTITY_SCHEMA_VERSION,
                    "spec_id": state.spec_id,
                    "head_commit": fresh_dispatch_plan.get("head_commit"),
                    "implementation_head_digest": fresh_dispatch_plan.get(
                        "implementation_head_digest"
                    ),
                },
                spec_id=state.spec_id,
                run_id=state.run_id,
                candidate_revision=fresh_candidate_revision,
            )
            if event.head != identity["implementation_head_digest"]:
                raise FeedbackValidationError("repair digest mismatch")
        except FeedbackValidationError:
            blocked = replace(
                event, role="parent", outcome="blocked",
                reason="scope_refusal", next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked)
        fresh = replace(
            state,
            phase=FeedbackPhase.AWAITING_FRESH_VERDICT,
            remediated_implementation_head_digest=event.head,
            remediated_candidate_revision=fresh_candidate_revision,
            remediated_verifier_head_commit=str(fresh_dispatch_plan["head_commit"]),
            remediated_containment_binding_digest=identity["containment_binding_digest"],
            repairer_id=event.actor_id,
        )
        excluded = [
            *state.implementer_ids,
            state.diagnostician_id,
            event.actor_id,
            state.initial_verifier_id,
        ]
        return _append_effects(
            fresh,
            _effect(
                fresh,
                "dispatch_verifier",
                "fresh-verifier:1",
                purpose="fresh",
                head=event.head,
                verifier_head_commit=fresh_dispatch_plan["head_commit"],
                ordinal=1,
                exclude_actor_ids=[item for item in excluded if item],
            ),
        )

    if event.kind == "recovery_admission":
        admission = admit_recovery(event.source or "", packet=state.packet)
        if not admission.admitted:
            rejected = replace(
                event,
                role="parent",
                outcome="blocked",
                reason=admission.reason,
                next_action="operator_controller_action",
            )
            return _terminal(
                state, admission.reason, human=True, event=rejected
            )
        return state

    if event.kind == "verdict":
        if event.role != "verifier" or event.verdict is None or not event.actor_id:
            valid = False
            validation_error = "invalid_verdict"
        else:
            try:
                validate_verifier_verdict(
                    event.verdict,
                    spec_id=state.spec_id,
                    implementation_head_digest=event.head or state.implementation_head_digest,
                    verifier_head_commit=(
                        state.remediated_verifier_head_commit
                        if state.phase is FeedbackPhase.AWAITING_FRESH_VERDICT
                        and state.remediated_verifier_head_commit
                        else state.verifier_head_commit
                    ),
                    expected_ac_ids=state.expected_ac_ids,
                    verifier_id=event.actor_id,
                    implementer_ids=state.implementer_ids,
                )
                valid = True
                validation_error = "invalid_verdict"
            except FeedbackValidationError as exc:
                valid = False
                validation_error = (
                    "legacy_verdict_identity"
                    if str(exc) == "legacy_verdict_missing_implementation_head_digest"
                    else "invalid_verdict"
                )

        verdict_event = replace(event, reason="ordinary_progress", next_action="continue")
        replacement_available = (
            state.phase
            in {
                FeedbackPhase.AWAITING_VERDICT,
                FeedbackPhase.AWAITING_REPLACEMENT_VERDICT,
            }
            and state.replacement_verifier_used == 0
        )
        rejection_event = replace(
            event,
            reason=validation_error,
            next_action=(
                "dispatch_replacement_verifier"
                if replacement_available
                else "operator_controller_action"
            ),
        )
        if not valid:
            state = _record_actor_effect(state, rejection_event)

        if state.phase in {
            FeedbackPhase.AWAITING_VERDICT,
            FeedbackPhase.AWAITING_REPLACEMENT_VERDICT,
        }:
            if not valid:
                if state.replacement_verifier_used == 0:
                    next_state = replace(
                        state,
                        phase=FeedbackPhase.AWAITING_REPLACEMENT_VERDICT,
                        replacement_verifier_used=1,
                    )
                    return _append_effects(
                        next_state,
                        _effect(
                            next_state,
                            "dispatch_verifier",
                            "replacement-verifier:1",
                            purpose="replacement",
                            head=state.implementation_head_digest,
                            ordinal=1,
                        ),
                    )
                blocked_event = replace(
                    event,
                    role="parent",
                    outcome="blocked",
                    reason=validation_error,
                    next_action="operator_controller_action",
                )
                return _terminal(
                    state, validation_error, human=True, event=blocked_event
                )
            if event.verdict.get("verdict") == "pass":
                state = _record_actor_effect(state, verdict_event)
                ready = replace(state, phase=FeedbackPhase.READY_FOR_INTEGRATION)
                return _append_effects(
                    ready,
                    _effect(
                        ready,
                        "enqueue_integration_broker",
                        "integration",
                        spec_id=state.spec_id,
                        head=state.implementation_head_digest,
                        candidate_revision=state.candidate_revision,
                        revision_kind="candidate",
                        fresh_main_validation=True,
                        owner="coordinator",
                        broker_entrypoint="IntegrationBroker.integrate_completed",
                    ),
                )
            if event.verdict.get("verdict") != "fail" or packet_inputs is None:
                state = _record_actor_effect(state, rejection_event)
                blocked_event = replace(
                    event,
                    role="parent",
                    outcome="blocked",
                    reason="invalid_verdict",
                    next_action="operator_controller_action",
                )
                return _terminal(
                    state, "invalid_verdict", human=True, event=blocked_event
                )
            try:
                packet = create_remediation_feedback(
                    run_id=state.run_id,
                    spec_id=state.spec_id,
                    implementation_head_digest=state.implementation_head_digest,
                    verdict=event.verdict,
                    verifier_id=event.actor_id,
                    expected_ac_ids=state.expected_ac_ids,
                    parent_key=parent_key,
                    implementer_ids=state.implementer_ids,
                    **{
                        key: packet_inputs[key]
                        for key in (
                            "candidate_revision", "dispatch_plan",
                            "containment_evidence", "evidence",
                            "reproduction_commands", "verification_commands",
                            "allowed_change_surface", "forbidden_surface",
                            "guardrails", "causal_confidence", "project_root",
                        )
                        if key in packet_inputs
                    },
                )
            except FeedbackValidationError:
                state = _record_actor_effect(state, rejection_event)
                if state.replacement_verifier_used == 0:
                    rejected = replace(
                        state,
                        phase=FeedbackPhase.AWAITING_REPLACEMENT_VERDICT,
                        replacement_verifier_used=1,
                    )
                    return _append_effects(
                        rejected,
                        _effect(
                            rejected,
                            "dispatch_verifier",
                            "replacement-verifier:1",
                            purpose="replacement",
                            head=state.implementation_head_digest,
                            ordinal=1,
                        ),
                    )
                blocked_event = replace(
                    event,
                    role="parent",
                    outcome="blocked",
                    reason="invalid_verdict",
                    next_action="operator_controller_action",
                )
                return _terminal(
                    state, "invalid_verdict", human=True, event=blocked_event
                )
            admission = admit_recovery(
                RecoverySource.VERIFIER_FAILURE.value, packet=packet
            )
            state = _record_actor_effect(state, verdict_event)
            admitted = replace(
                state,
                phase=FeedbackPhase.PACKET_ADMITTED,
                packet=admission.packet,
                initial_verifier_id=event.actor_id,
            )
            return _append_effects(
                admitted,
                _effect(
                    admitted,
                    "persist_packet",
                    f"packet:{packet.source_verdict_digest}:1",
                    packet=packet.record(),
                ),
            )

        if state.phase is FeedbackPhase.AWAITING_FRESH_VERDICT:
            disallowed_verifiers = {
                *state.implementer_ids,
                state.initial_verifier_id,
                state.remediator_id,
                state.diagnostician_id,
                state.repairer_id,
            }
            if (
                not valid
                or event.verdict.get("verdict") not in {"pass", "fail"}
                or event.head != state.remediated_implementation_head_digest
                or event.actor_id in disallowed_verifiers
            ):
                if valid:
                    state = _record_actor_effect(state, verdict_event)
                blocked_event = replace(
                    event,
                    role="parent",
                    outcome="blocked",
                    reason="fresh_verifier_failure",
                    next_action="operator_controller_action",
                )
                return _terminal(
                    state, "fresh_verifier_failure", human=True, event=blocked_event
                )
            if event.verdict.get("verdict") == "fail":
                if state.packet is None:
                    blocked_event = replace(event, role="parent", outcome="blocked", reason="fresh_verifier_failure", next_action="operator_controller_action")
                    return _terminal(state, "fresh_verifier_failure", human=True, event=blocked_event)
                resilience = verifier_failure_resilience(
                    state.packet, event.verdict, max_rounds=state.remediation_limit
                )
                state = _record_actor_effect(state, verdict_event)
                rung = _effect(
                    state, "resilience_rung", f"resilience:{resilience.effect_key}",
                    failure_class=resilience.failure_class, rung=resilience.rung,
                    outcome=("dispatched" if resilience.terminal is None else "blocked"),
                    evidence_refs=list(resilience.evidence_refs),
                )
                if resilience.terminal is not None or state.remediation_used >= state.remediation_limit:
                    blocked_event = replace(event, role="parent", outcome="blocked", reason="fresh_verifier_failure", next_action="operator_controller_action")
                    return _append_effects(_terminal(state, "fresh_verifier_failure", human=True, event=blocked_event), rung)
                # A new packet is deliberately required for the changed head;
                # the parent supplies fresh containment/dispatch evidence.
                if packet_inputs is None:
                    blocked_event = replace(event, role="parent", outcome="blocked", reason="fresh_verifier_failure", next_action="operator_controller_action")
                    return _append_effects(_terminal(state, "fresh_verifier_failure", human=True, event=blocked_event), rung)
                try:
                    fresh_inputs = dict(packet_inputs)
                    for base in ("candidate_revision", "dispatch_plan", "containment_evidence"):
                        fresh = f"fresh_{base}"
                        if fresh in fresh_inputs:
                            fresh_inputs[base] = fresh_inputs[fresh]
                    packet = create_remediation_feedback(
                        run_id=state.run_id, spec_id=state.spec_id,
                        implementation_head_digest=state.remediated_implementation_head_digest,
                        verdict=event.verdict, verifier_id=event.actor_id,
                        expected_ac_ids=state.expected_ac_ids, parent_key=parent_key,
                        implementer_ids=state.implementer_ids,
                        **{key: fresh_inputs[key] for key in (
                            "candidate_revision", "dispatch_plan", "containment_evidence", "evidence",
                            "reproduction_commands", "verification_commands", "allowed_change_surface",
                            "forbidden_surface", "guardrails", "causal_confidence", "project_root",
                        ) if key in fresh_inputs},
                    )
                except FeedbackValidationError:
                    blocked_event = replace(event, role="parent", outcome="blocked", reason="fresh_verifier_failure", next_action="operator_controller_action")
                    return _append_effects(_terminal(state, "fresh_verifier_failure", human=True, event=blocked_event), rung)
                admitted = replace(state, phase=FeedbackPhase.PACKET_ADMITTED, packet=packet,
                    remediation_mode=None, initial_verifier_id=event.actor_id)
                return _append_effects(admitted, rung, _effect(admitted, "persist_packet",
                    f"packet:{packet.source_verdict_digest}:2", packet=packet.record()))
            state = _record_actor_effect(state, verdict_event)
            ready = replace(state, phase=FeedbackPhase.READY_FOR_INTEGRATION)
            return _append_effects(
                ready,
                _effect(
                    ready,
                    "enqueue_integration_broker",
                    "integration",
                    spec_id=state.spec_id,
                    head=state.remediated_implementation_head_digest,
                    candidate_revision=state.remediated_candidate_revision,
                    remediated_candidate_revision=state.remediated_candidate_revision,
                    revision_kind="remediated",
                    fresh_main_validation=True,
                    owner="coordinator",
                    broker_entrypoint="IntegrationBroker.integrate_completed",
                ),
            )

    if (
        event.kind == "select_remediation"
        and state.phase is FeedbackPhase.PACKET_ADMITTED
    ):
        if (
            event.role != "parent"
            or event.remediation_mode not in REMEDIATION_MODES
            or state.remediation_used >= state.remediation_limit
        ):
            blocked_event = replace(
                event,
                role="parent",
                outcome="blocked",
                reason="scope_refusal",
                next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked_event)
        selected = replace(
            state,
            phase=FeedbackPhase.REMEDIATION_DISPATCHING,
            remediation_mode=event.remediation_mode,
            remediation_used=state.remediation_used + 1,
        )
        return _append_effects(
            selected,
            _effect(
                selected,
                "dispatch_remediation",
                f"remediation:{state.remediation_used + 1}",
                mode=event.remediation_mode,
                packet=state.packet.record() if state.packet else None,
                original_authority=list(state.original_authority),
            ),
        )

    if (
        event.kind == "remediation_dispatched"
        and state.phase is FeedbackPhase.REMEDIATION_DISPATCHING
    ):
        if event.role != "parent":
            blocked_event = replace(
                event,
                role="parent",
                outcome="blocked",
                reason="scope_refusal",
                next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked_event)
        return replace(state, phase=FeedbackPhase.REMEDIATION_RUNNING)

    if event.kind == "remediation_result" and state.phase in {
        FeedbackPhase.REMEDIATION_DISPATCHING,
        FeedbackPhase.REMEDIATION_RUNNING,
    }:
        state = _record_actor_effect(state, event)
        if event.role != "remediator":
            blocked_event = replace(
                event,
                role="parent",
                outcome="blocked",
                reason="scope_refusal",
                next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked_event)
        fresh_candidate_revision = (
            packet_inputs.get("fresh_candidate_revision")
            if packet_inputs is not None else None
        )
        fresh_dispatch_plan = (
            packet_inputs.get("fresh_dispatch_plan")
            if packet_inputs is not None else None
        )
        fresh_containment_evidence = (
            packet_inputs.get("fresh_containment_evidence")
            if packet_inputs is not None else None
        )
        if (
            event.outcome != "completed"
            or not event.head
            or not isinstance(fresh_candidate_revision, str)
            or not GIT_OBJECT_ID_RE.fullmatch(fresh_candidate_revision)
            or fresh_candidate_revision == state.candidate_revision
        ):
            reason = (
                "unchanged_head"
                if fresh_candidate_revision == state.candidate_revision
                else "remediation_failure"
            )
            blocked_event = replace(
                event,
                role="parent",
                outcome="blocked",
                reason=reason,
                next_action="operator_controller_action",
            )
            return _terminal(state, reason, human=True, event=blocked_event)
        if not event.actor_id or state.packet is None:
            blocked_event = replace(
                event,
                role="parent",
                outcome="blocked",
                reason="remediation_failure",
                next_action="operator_controller_action",
            )
            return _terminal(
                state, "remediation_failure", human=True, event=blocked_event
            )
        try:
            validate_changed_surface(state.packet, event.changed_paths)
            if not isinstance(fresh_dispatch_plan, Mapping) or not isinstance(
                fresh_containment_evidence, Mapping
            ):
                raise FeedbackValidationError("fresh verifier surface is missing")
            identity = validate_dispatch_identity(
                dispatch_plan=dict(fresh_dispatch_plan),
                containment_evidence=dict(fresh_containment_evidence),
                verdict={
                    "identity_schema_version": VERIFIER_IDENTITY_SCHEMA_VERSION,
                    "spec_id": state.spec_id,
                    "head_commit": fresh_dispatch_plan.get("head_commit"),
                    "implementation_head_digest": fresh_dispatch_plan.get(
                        "implementation_head_digest"
                    ),
                },
                spec_id=state.spec_id,
                run_id=state.run_id,
                candidate_revision=fresh_candidate_revision,
            )
            if event.head != identity["implementation_head_digest"]:
                raise FeedbackValidationError("remediation digest mismatch")
        except FeedbackValidationError:
            blocked_event = replace(
                event,
                role="parent",
                outcome="blocked",
                reason="scope_refusal",
                next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked_event)
        fresh = replace(
            state,
            phase=FeedbackPhase.AWAITING_FRESH_VERDICT,
            remediated_implementation_head_digest=event.head,
            remediated_candidate_revision=fresh_candidate_revision,
            remediated_verifier_head_commit=str(fresh_dispatch_plan["head_commit"]),
            remediated_containment_binding_digest=identity[
                "containment_binding_digest"
            ],
            remediator_id=event.actor_id,
        )
        return _append_effects(
            fresh,
            _effect(
                fresh,
                "dispatch_verifier",
                "fresh-verifier:1",
                purpose="fresh",
                head=event.head,
                verifier_head_commit=fresh_dispatch_plan["head_commit"],
                ordinal=1,
                exclude_actor_ids=[state.initial_verifier_id, event.actor_id],
            ),
        )

    if event.kind == "dispatch_failed":
        blocked_event = replace(
            event,
            role="parent",
            outcome="blocked",
            reason="dispatch_failure",
            next_action="inspect_adapter",
        )
        return _terminal(state, "dispatch_failure", human=True, event=blocked_event)

    if (
        event.kind == "integration_result"
        and state.phase is FeedbackPhase.READY_FOR_INTEGRATION
    ):
        if event.role != "parent":
            blocked_event = replace(
                event,
                role="parent",
                outcome="blocked",
                reason="scope_refusal",
                next_action="authorize_scope",
            )
            return _terminal(state, "scope_refusal", human=True, event=blocked_event)
        if event.outcome == "completed":
            verified_head = (
                state.remediated_implementation_head_digest
                or state.implementation_head_digest
            )
            verified_revision = state.remediated_candidate_revision
            if verified_revision is not None and (
                not GIT_OBJECT_ID_RE.fullmatch(verified_revision)
                or event.applied_revision != verified_revision
            ):
                blocked_event = replace(
                    event,
                    role="parent",
                    outcome="blocked",
                    reason="verifier_identity_mismatch",
                    next_action="operator_controller_action",
                )
                return _terminal(
                    state, "verifier_identity_mismatch", human=False,
                    event=blocked_event,
                )
            if event.head != verified_head and (
                event.head is not None or state.blocked_attempt is not None
            ):
                blocked_event = replace(
                    event,
                    role="parent",
                    outcome="blocked",
                    reason="verifier_identity_mismatch",
                    next_action="operator_controller_action",
                )
                return _terminal(
                    state,
                    "verifier_identity_mismatch",
                    human=False,
                    event=blocked_event,
                )
            done = replace(
                state,
                phase=FeedbackPhase.TERMINAL_DONE,
                terminal_reason="ordinary_progress",
            )
            return _append_effects(
                done,
                _effect(
                    done,
                    "record_outcome",
                    f"parent-outcome:{event.key}",
                    record=normalized_outcome_record(
                        done, event, terminal_outcome="done"
                    ),
                ),
                _effect(
                    done,
                    "terminal_resolution",
                    "terminal:done",
                    outcome="done",
                    fresh_main_validation=True,
                ),
            )
        blocked_event = replace(
            event,
            role="parent",
            outcome="blocked",
            reason="adapter_failure",
            next_action="inspect_adapter",
        )
        return _terminal(state, "adapter_failure", human=True, event=blocked_event)

    return state


def _deliver_pending_effects(
    adapter: FeedbackRuntimeAdapter,
    state: FeedbackState,
    *,
    parent_key: bytes,
) -> FeedbackState:
    """Reconcile persisted effects, including restart after acknowledgement loss."""
    if state.failed_effect_keys:
        return state
    for effect in state.pending_effects:
        if (
            effect.key in state.delivered_effect_keys
            or effect.key in state.failed_effect_keys
        ):
            continue
        try:
            result_event = adapter.execute_effect(effect, idempotency_key=effect.key)
        except Exception:  # noqa: BLE001 - adapters may surface provider-neutral exceptions.
            state = replace(
                state,
                pending_effects=tuple(
                    item for item in state.pending_effects if item.key != effect.key
                ),
                failed_effect_keys=state.failed_effect_keys + (effect.key,),
            )
            failure_event = NormalizedFeedbackEvent(
                key=f"adapter-failure:{hashlib.sha256(effect.key.encode()).hexdigest()[:24]}",
                kind="dispatch_failed",
                role="parent",
                outcome="failed",
                reason="adapter_failure",
                next_action="inspect_adapter",
            )
            state = reduce_feedback_event(state, failure_event, parent_key=parent_key)
            adapter.save_state(state)
            return state
        state = replace(
            state,
            delivered_effect_keys=state.delivered_effect_keys + (effect.key,),
            pending_effects=tuple(
                item for item in state.pending_effects if item.key != effect.key
            ),
        )
        if result_event is not None:
            if not isinstance(result_event, NormalizedFeedbackEvent):
                raise FeedbackValidationError("adapter returned invalid result event")
            state = reduce_feedback_event(
                state, result_event, parent_key=parent_key
            )
        adapter.save_state(state)
    return state


def reconcile_feedback(
    adapter: FeedbackRuntimeAdapter,
    initial_state: FeedbackState,
    *,
    parent_key: bytes,
    events: Iterable[NormalizedFeedbackEvent] | None = None,
    packet_inputs: Mapping[str, Any] | None = None,
) -> FeedbackState:
    """Persist reducer state before executing each keyed effect, then acknowledge it."""
    state = adapter.load_state(initial_state.run_id) or initial_state
    state = _deliver_pending_effects(adapter, state, parent_key=parent_key)
    for event in events if events is not None else adapter.poll_events(state.run_id):
        state = reduce_feedback_event(
            state, event, parent_key=parent_key, packet_inputs=packet_inputs
        )
        adapter.save_state(state)
        state = _deliver_pending_effects(adapter, state, parent_key=parent_key)
    return state
