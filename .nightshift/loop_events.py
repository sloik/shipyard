#!/usr/bin/env python3
"""
Append-only NDJSON event logging for Nightshift loop runs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# SPEC-196 deliberately keeps this vocabulary small.  Event payloads must use
# these identifiers rather than arbitrary agent prose so cross-run analytics
# stays safe to publish.
PHASE_IDS = frozenset({
    "admission", "preflight", "context_load", "test_planning", "test_writing",
    "implementation", "review", "validation", "evidence_gate", "recovery",
    "merge", "terminal_recording",
})
PHASE_MEASUREMENT_STATES = frozenset({"measured", "skipped", "interrupted", "unavailable"})


def emit_phase_event(log: "RunEventLog", event: str, spec_id: str, phase: str, **payload) -> None:
    """Emit a controlled phase boundary without accepting private run detail."""
    if event not in {"phase_started", "phase_finished"}:
        raise ValueError("phase event must be phase_started or phase_finished")
    if phase not in PHASE_IDS:
        raise ValueError("unknown phase id")
    state = payload.get("measurement_state")
    if event == "phase_finished" and state not in PHASE_MEASUREMENT_STATES:
        raise ValueError("phase finish requires a controlled measurement state")
    if set(payload) - {"measurement_state", "ts"}:
        raise ValueError("unapproved phase event field")
    log.emit(event, spec_id=spec_id, phase=phase, **payload)


def emit_token_usage_event(log: "RunEventLog", *, spec_id: str, **kwargs) -> "TokenUsageResult":
    """SPEC-298: normalize and, if accepted, persist one token-usage event.

    Delegates the privacy/consistency adapter boundary to
    ``token_usage.normalize_provider_usage``. A rejected input is never
    written to the run event stream (R2); this function still returns the
    ``TokenUsageResult`` so the caller can surface the deterministic
    rejection reason.
    """
    from token_usage import normalize_provider_usage

    result = normalize_provider_usage(run_id=log.run_id, spec_id=spec_id, **kwargs)
    if result.accepted:
        event = dict(result.event)
        event.pop("spec_id", None)
        log.emit("token_usage", spec_id=spec_id, **event)
    return result


STEP_NAMES: Dict[int, str] = {
    1: "preflight",
    2: "task_selection",
    3: "context_loading",
    4: "test_planning",
    5: "test_writing",
    6: "plan_review",
    7: "implementation",
    8: "validation",
    9: "completion_verification",
    10: "post_review",
    11: "circuit_breaker",
    12: "commit_changelog",
    13: "metrics_logging",
    14: "report_generation",
    15: "post_run",
    16: "loop_exit",
}

# SPEC-188 recovery events are deliberately small, categorical records.  They
# share the run event stream; this module never changes lifecycle state.
RECOVERY_EVENT_TYPES = frozenset({
    "capability_probe",
    "recovery_attempt_started",
    "recovery_attempt_finished",
    "recovery_escalated",
    "block_evaluated",
    "run_resolved",
})
RECOVERY_OUTCOMES = frozenset({"passed", "failed", "skipped", "succeeded", "exhausted"})
RESILIENCE_CLASSES = frozenset({"verifier_fail", "premise_dispute", "evidence_gap", "transport_stall"})
RESILIENCE_OUTCOMES = frozenset({"continue", "dispatched", "blocked", "done", "exhausted"})

# SPEC-235 actor-attempt events remain distinct from the parent lifecycle
# decision.  Payloads contain controlled values and hash-bound relative refs;
# conclusions and raw execution data stay outside the run stream.
FEEDBACK_ROLES = frozenset({
    "implementer", "diagnostician", "repairer", "verifier", "remediator", "parent"
})
FEEDBACK_OUTCOMES = frozenset({
    "completed", "blocked", "refused", "failed", "stalled", "unavailable",
    "passed", "cancelled",
})


def emit_feedback_outcome(log: "RunEventLog", record: Dict) -> None:
    from recovery_convergence import DiagnosisClass, RepairRoute
    from verifier_feedback import (
        CONTROLLED_REASONS, NEXT_ACTIONS, SHA256_RE, FeedbackPhase,
        RecoverySource, _validate_relative_path,
    )

    allowed = {
        "schema_version", "spec_id", "run_id", "role", "agent_outcome", "reason",
        "head_digest", "artifact_refs", "idempotency_key", "attempt_ordinal",
        "duration_s", "terminal_outcome", "human_action_required", "next_action",
        "recovery_source", "diagnosis_class", "causal_confidence",
        "candidate_preserved", "repair_route", "diagnostician_allowance",
        "repair_allowance", "operator_action", "delivery_phase",
    }
    if set(record) != allowed:
        raise ValueError("feedback outcome fields do not match the closed schema")
    if record["role"] not in FEEDBACK_ROLES or record["agent_outcome"] not in FEEDBACK_OUTCOMES:
        raise ValueError("invalid feedback role or outcome")
    if record["reason"] not in CONTROLLED_REASONS or record["next_action"] not in NEXT_ACTIONS:
        raise ValueError("invalid feedback reason or next action")
    if record["head_digest"] is not None and not SHA256_RE.fullmatch(record["head_digest"]):
        raise ValueError("invalid feedback head digest")
    for item in record["artifact_refs"]:
        _validate_relative_path(item["path"], "feedback artifact reference")
        if not SHA256_RE.fullmatch(item["sha256"]):
            raise ValueError("invalid feedback artifact digest")
    for key in ("diagnostician_allowance", "repair_allowance"):
        allowance = record[key]
        if (
            set(allowance) != {"used", "limit"}
            or allowance["limit"] not in {1, 2}
            or not isinstance(allowance["used"], int)
            or allowance["used"] < 0
            or allowance["used"] > allowance["limit"]
        ):
            raise ValueError("invalid feedback allowance")
    if record["recovery_source"] not in {None, *(item.value for item in RecoverySource)}:
        raise ValueError("invalid feedback recovery source")
    if record["diagnosis_class"] not in {None, *(item.value for item in DiagnosisClass)}:
        raise ValueError("invalid feedback diagnosis class")
    if record["causal_confidence"] not in {None, "demonstrated", "supported", "uncertain"}:
        raise ValueError("invalid feedback causal confidence")
    if record["repair_route"] not in {None, *(item.value for item in RepairRoute)}:
        raise ValueError("invalid feedback repair route")
    if not isinstance(record["candidate_preserved"], bool):
        raise ValueError("candidate_preserved must be boolean")
    if record["operator_action"] not in {None, *NEXT_ACTIONS}:
        raise ValueError("invalid feedback operator action")
    if record["delivery_phase"] not in {item.value for item in FeedbackPhase}:
        raise ValueError("invalid feedback delivery phase")
    log.emit("agent_outcome", spec_id=record["spec_id"], **{
        key: value for key, value in record.items() if key != "spec_id"
    })


def validate_recovery_event(event_type: str, payload: Dict) -> None:
    """Reject unbounded recovery telemetry before it enters the event stream."""
    if event_type not in RECOVERY_EVENT_TYPES:
        raise ValueError("not a controlled recovery event")
    for key, value in payload.items():
        if key in {"spec_id", "ts"}:
            continue
        if key not in {
            "capability", "outcome", "eligible", "safe", "fresh_worker",
            "duration_s", "attempt", "evidence_ref", "evidence_hash",
            "block_reason", "sink_status", "run_sequence",
        }:
            raise ValueError(f"unapproved recovery field: {key}")
        if isinstance(value, str) and ("/" in value or "\\" in value):
            raise ValueError("recovery telemetry may not contain paths")
        if key == "outcome" and value not in RECOVERY_OUTCOMES:
            raise ValueError("invalid recovery outcome")
        if key in {"eligible", "safe", "fresh_worker"} and not isinstance(value, bool):
            raise ValueError(f"{key} must be boolean")
        if key in {"duration_s", "attempt", "run_sequence"} and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"{key} must be a non-negative number")


def emit_recovery_event(log: "RunEventLog", event_type: str, spec_id: str, **payload) -> None:
    """Append one validated recovery observation to the existing RunEventLog."""
    validate_recovery_event(event_type, {"spec_id": spec_id, **payload})
    log.emit(event_type, spec_id=spec_id, **payload)


def emit_resilience_rung(
    log: "RunEventLog", spec_id: str, *, failure_class: str, rung: int,
    outcome: str, evidence_refs: list[str] | None = None,
) -> None:
    """Record one privacy-safe, class-specific recovery rung (SPEC-266)."""
    if failure_class not in RESILIENCE_CLASSES:
        raise ValueError("unknown resilience class")
    if not isinstance(rung, int) or isinstance(rung, bool) or rung < 0:
        raise ValueError("resilience rung must be a non-negative integer")
    if outcome not in RESILIENCE_OUTCOMES:
        raise ValueError("unknown resilience outcome")
    refs = evidence_refs or []
    if not all(isinstance(item, str) and "/" not in item and "\\" not in item for item in refs):
        raise ValueError("resilience evidence refs must be controlled identifiers")
    log.emit("resilience_rung", spec_id=spec_id, resilience_class=failure_class,
             rung=rung, outcome=outcome, evidence_refs=refs)


# SPEC-NS-KIT-108: which lane a run used (`small` = worker-small.md plus the condensed
# parent checklist, `full` = the whole loop) and the lane-relevant counters.  One bounded
# event per run, written to the same run stream the other emitters use; the existing
# `verification_report.py throughput-report` reads it back.  An unmeasured counter is the
# string `unavailable`, never 0 (the SPEC-NS-KIT-002-001 convention).
LANES = frozenset({"small", "full"})
LANE_UNAVAILABLE = "unavailable"
LANE_COUNTER_FIELDS = ("parent_tool_calls", "worker_wall_s", "verifier_wall_s", "verifier_dispatches")


def _lane_counter(name: str, value, *, integer: bool):
    if value == LANE_UNAVAILABLE:
        return value
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    if ok and integer and int(value) != value:
        ok = False
    if not ok:
        raise ValueError(f"{name} must be a non-negative {'integer' if integer else 'number'} or 'unavailable'")
    return int(value) if integer else round(float(value), 3)


def normalize_delivery_observation(row):
    """Project optional observations to bounded public fields; never authorize work."""
    import math
    import re
    from datetime import datetime
    if not isinstance(row, dict):
        return None
    def identifier(value):
        return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value) else None
    keys = ('repository_id', 'project_id', 'spec_id', 'run_id', 'observation_id')
    clean = {key: identifier(row.get(key)) for key in keys}
    if not all(clean.values()):
        return None
    clean['observation_origin'] = 'receipt' if row.get('observation_origin') == 'receipt' else 'emitted'
    for key in ('attempt_id', 'action_id'):
        if row.get(key) is not None and identifier(row.get(key)) is None:
            return None
    clean.update(event='delivery_observed', schema_version='1.0.0',
                 attempt_id=identifier(row.get('attempt_id')), action_id=identifier(row.get('action_id')))
    for key in ('source_receipt_digest', 'demand_receipt_digest', 'kit_fingerprint'):
        value = row.get(key)
        clean[key] = value if isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) else None
    version = row.get('kit_version')
    clean['kit_version'] = version if isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', version) else None
    clean['stage'] = row.get('stage') if isinstance(row.get('stage'), str) and row.get('stage') in {
        'ready_restored', 'candidate_accepted', 'integrated', 'projection_complete', 'released'} else None
    clean['disposition'] = row.get('disposition') if isinstance(row.get('disposition'), str) and row.get('disposition') in {
        'consumed', 'native_fallback', 'not_offered', 'abandoned', 'refused', 'offered'} else None
    clean['eligibility'] = row.get('eligibility') if isinstance(row.get('eligibility'), bool) else None
    reasons = {'missing_transport', 'identity_match', 'identity_mismatch', 'ledger_disabled',
               'head_proof_untrusted', 'ledger_error', 'ledger_module_unavailable',
               'no_supported_proof', 'contract_binding_missing_or_changed', 'recovery_boundary_mismatch',
               'not_offered', 'abandoned', 'native_failed', 'native_passed', 'input_policy_unresolved',
               'untrusted_receipt', 'identity_changed', 'partial_coverage', 'stale_receipt'}
    clean['reason_code'] = row.get('reason_code') if isinstance(row.get('reason_code'), str) and row.get('reason_code') in reasons else None
    for key in ('product_outcome', 'diagnostic_outcome', 'admissibility_outcome', 'settlement_outcome'):
        clean[key] = row.get(key) if isinstance(row.get(key), str) and row.get(key) in {'passed', 'failed', 'accepted', 'refused', 'unknown'} else None
    def number(value):
        try:
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
        except (OverflowError, ValueError):
            return None
    measurements = row.get('measurements') if isinstance(row.get('measurements'), dict) else {}
    clean['measurements'] = {key: number(measurements.get(key)) for key in
        ('native_seconds', 'parent_tool_calls', 'worker_wall_s', 'verifier_wall_s', 'spend')}
    clean['native_age_s'] = number(row.get('native_age_s'))
    clean['source_native_seconds'] = number(row.get('source_native_seconds'))
    for key in ('native_created_at', 'started_at', 'ended_at'):
        value = row.get(key)
        clean[key] = None
        if isinstance(value, str) and len(value) <= 40:
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is not None:
                    clean[key] = value
            except ValueError:
                pass
    return clean


def delivery_observation_context(root):
    """Opaque association from the caller's explicit install and existing Git identity."""
    import hashlib
    import subprocess
    from pathlib import Path
    try:
        root = Path(root).resolve()
        git = subprocess.run(['git', '-C', str(root), 'rev-parse', '--path-format=absolute',
            '--git-common-dir', '--show-toplevel'], capture_output=True, text=True, check=True, timeout=2)
        common, checkout = git.stdout.splitlines()
        common, checkout = Path(common).resolve(), Path(checkout).resolve()
        component = root.parent if root.name == '.nightshift' else root
        relative = component.relative_to(checkout).as_posix()
        repository = hashlib.sha256(str(common).encode()).hexdigest()
        context = {'repository_id': repository,
                   'project_id': hashlib.sha256((repository + ':' + relative).encode()).hexdigest()}
    except Exception:
        return {}
    try:
        import yaml
        config = root / 'config.yaml'
        if config.is_file() and not config.is_symlink() and config.stat().st_size <= 65536:
            for doc in yaml.safe_load_all(config.read_text(encoding='utf-8')):
                if isinstance(doc, dict) and 'kit_version' in doc:
                    context['kit_version'] = doc['kit_version']
        manifest = root / 'release-manifest.json'
        if manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size <= 2 * 1024 * 1024:
            context['kit_fingerprint'] = json.loads(manifest.read_text(encoding='utf-8')).get('fingerprint')
    except Exception:
        pass
    return context


def observe_delivery_boundary(root, spec_id, *, run_id, action_id, **fields):
    """Observe a completed parent boundary, never change its authority or return value."""
    import hashlib
    try:
        data = {**delivery_observation_context(root), **fields, 'spec_id': spec_id,
                'run_id': run_id, 'action_id': action_id}
        if data.get('observation_id') is None:
            normalized = normalize_delivery_observation({**data, 'observation_id': 'pending'})
            if normalized is None:
                return False
            identity = {key: normalized[key] for key in ('repository_id', 'project_id', 'spec_id',
                'run_id', 'attempt_id', 'action_id', 'stage', 'disposition', 'source_receipt_digest',
                'demand_receipt_digest', 'product_outcome', 'diagnostic_outcome', 'admissibility_outcome', 'settlement_outcome')}
            data['observation_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return emit_delivery_observation(open_run_log(root, run_id), spec_id, **{key: value for key, value in data.items()
            if key not in {'spec_id', 'run_id'}})
    except Exception:
        return False


def emit_delivery_observation(log, spec_id, **fields):
    """Advisory only: malformed data and optional sink failures cannot affect callers."""
    try:
        row = normalize_delivery_observation({**fields, 'spec_id': spec_id, 'run_id': log.run_id})
        if row is None:
            return False
        log.emit('delivery_observed', spec_id, **{key: value for key, value in row.items()
            if key not in {'event', 'spec_id', 'run_id'}})
        return True
    except Exception:
        return False


def emit_lane_event(
    log: "RunEventLog", spec_id: str, *, lane: str, parent_tool_calls, worker_wall_s,
    verifier_wall_s, verifier_dispatches, redispatch_reasons=(),
) -> dict:
    """Append one `lane_recorded` event: the lane tag plus every lane counter (all required)."""
    from record_metrics import REDISPATCH_REASON_ENUM

    if lane not in LANES:
        raise ValueError(f"lane must be one of {sorted(LANES)}")
    counters = {
        "parent_tool_calls": _lane_counter("parent_tool_calls", parent_tool_calls, integer=True),
        "worker_wall_s": _lane_counter("worker_wall_s", worker_wall_s, integer=False),
        "verifier_wall_s": _lane_counter("verifier_wall_s", verifier_wall_s, integer=False),
        "verifier_dispatches": _lane_counter("verifier_dispatches", verifier_dispatches, integer=True),
    }
    reasons = list(redispatch_reasons)
    if any(item not in REDISPATCH_REASON_ENUM for item in reasons):
        raise ValueError(f"redispatch reasons must be within {sorted(REDISPATCH_REASON_ENUM)}")
    dispatches = counters["verifier_dispatches"]
    if isinstance(dispatches, int) and len(reasons) > max(dispatches - 1, 0):
        raise ValueError("more redispatch reasons than redispatches")
    log.emit("lane_recorded", spec_id=spec_id, lane=lane, redispatch_reasons=reasons, **counters)
    return {"lane": lane, "redispatch_reasons": reasons, **counters}


def record_official_followup_decisions(
    log: "RunEventLog", *, source_spec_id: str, terminal_resolution: str,
    discovery_phase: str, evidence_ref: str, outcomes: list[str], recorded_at: str,
) -> list[dict]:
    """Write sealed follow-up decisions and one bounded event per resolution.

    This is the production lifecycle seam: callers use it only after the
    normal follow-up processor has reached controlled outcomes.  Event payloads
    carry counts and hashes, not report text or paths.
    """
    from followup_decisions import record_followup_decisions

    decisions, created = record_followup_decisions(
        log.nightshift_dir,
        run_id=log.run_id,
        source_spec_id=source_spec_id,
        terminal_resolution=terminal_resolution,
        discovery_phase=discovery_phase,
        evidence_ref=evidence_ref,
        outcomes=outcomes,
        recorded_at=recorded_at,
    )
    if created:
        log.emit(
            "followup_decisions_recorded",
            spec_id=source_spec_id,
            terminal_resolution=terminal_resolution,
            decision_count=len(decisions),
            zero_suggestion=not outcomes,
            decision_digest=hashlib.sha256(
                "".join(item["operation_key"] for item in decisions).encode("utf-8")
            ).hexdigest(),
        )
    return decisions


def process_official_followup(
    log: "RunEventLog", *, source_spec_id: str, terminal_resolution: str,
    discovery_phase: str, classification: dict, evidence_ref: str, outcome: str,
    child_spec_id: str | None = None, specs_dir: Path | None = None,
    recorded_at: str,
) -> dict:
    """The single executable processor used by every terminal follow-up route."""
    from followup_decisions import seal_official_decision

    record, created = seal_official_decision(
        log.nightshift_dir, run_id=log.run_id, source_spec_id=source_spec_id,
        terminal_resolution=terminal_resolution, discovery_phase=discovery_phase,
        classification=classification, evidence_ref=evidence_ref, outcome=outcome,
        child_spec_id=child_spec_id, specs_dir=specs_dir, recorded_at=recorded_at,
    )
    if created:
        log.emit("official_followup_processed", spec_id=source_spec_id,
                 terminal_resolution=terminal_resolution, outcome=outcome,
                 child_sealed=child_spec_id is not None,
                 cause_class=record["classification"]["cause_class"])
    return record


# These route functions are the production boundaries called by the parent
# lifecycle handlers.  Keeping them executable (instead of only documenting
# the helper in LOOP.md) makes each terminal route independently testable.
def process_normal_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="done", **kwargs)

def process_noop_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="noop", **kwargs)

def process_partial_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="partial", **kwargs)

def process_blocked_unblock_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="unblock", **kwargs)

def process_verifier_warning_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="verifier_warning", **kwargs)

def process_material_scope_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="material_scope", **kwargs)

def process_integration_failure_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="integration_failure", **kwargs)

def process_post_release_followup(log: "RunEventLog", **kwargs) -> dict:
    return process_official_followup(log, terminal_resolution="post_release", **kwargs)


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def generate_run_id() -> str:
    return "run-" + datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def load_events(events_file: Path) -> List[Dict]:
    events: List[Dict] = []
    try:
        with open(events_file, "r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    _warn(
                        f"warning: malformed event line {line_number} in "
                        f"{events_file}: {exc}"
                    )
                    continue
                if isinstance(event, dict):
                    events.append(event)
                else:
                    _warn(
                        f"warning: non-object event line {line_number} in "
                        f"{events_file}"
                    )
    except FileNotFoundError:
        return []
    except OSError as exc:
        _warn(f"warning: failed reading events from {events_file}: {exc}")
    return events


def tail_events(events_file: Path, last_n: int = 20) -> List[Dict]:
    if last_n <= 0:
        return []

    try:
        with open(events_file, "rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            if file_size == 0:
                return []

            chunk_size = 4096
            chunks = []
            lines_needed = last_n + 1
            position = file_size

            while position > 0 and lines_needed > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(-read_size, 1 if position + read_size != file_size else 2)
                chunk = handle.read(read_size)
                chunks.append(chunk)
                handle.seek(position, 0)
                lines_needed -= chunk.count(b"\n")

            data = b"".join(reversed(chunks)).decode("utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        _warn(f"warning: failed tailing events from {events_file}: {exc}")
        return []

    events: List[Dict] = []
    lines = data.splitlines()
    start_line = max(0, len(lines) - last_n)
    for line_number, line in enumerate(lines[start_line:], start=start_line + 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError as exc:
            _warn(
                f"warning: malformed event line {line_number} in "
                f"{events_file}: {exc}"
            )
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            _warn(
                f"warning: non-object event line {line_number} in "
                f"{events_file}"
            )
    return events


class RunEventLog:
    def __init__(self, nightshift_dir: Path, run_id: str):
        self.nightshift_dir = Path(nightshift_dir)
        self.run_id = run_id
        self.events_file = self.nightshift_dir / "runs" / run_id / "events.jsonl"

    def emit(self, event_type: str, spec_id=None, **kwargs) -> None:
        event = {
            "ts": kwargs.pop("ts", _iso_utc_now()),
            "event": event_type,
            "run_id": self.run_id,
            "spec_id": spec_id,
        }
        event.update(kwargs)

        try:
            self.events_file.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            with open(self.events_file, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError as exc:
            _warn(f"warning: failed to write event to {self.events_file}: {exc}")

    def read_all(self) -> List[Dict]:
        return load_events(self.events_file)

    def find_last_step(self, spec_id: str) -> Optional[Dict]:
        for event in reversed(self.read_all()):
            if (
                event.get("event") == "step_completed"
                and event.get("spec_id") == spec_id
            ):
                return event
        return None

    def find_resume_point(self, spec_id: str) -> Optional[int]:
        last_step = self.find_last_step(spec_id)
        if last_step is None:
            return None

        step = last_step.get("step")
        if isinstance(step, int):
            return step + 1
        return None


def open_run_log(nightshift_dir: Path, run_id: Optional[str] = None) -> RunEventLog:
    return RunEventLog(nightshift_dir=nightshift_dir, run_id=run_id or generate_run_id())


def _count_arg(raw: str):
    return raw if raw == LANE_UNAVAILABLE else float(raw)


def main(argv=None) -> int:
    """`loop_events.py lane ...`: the parent's one-line emitter for the lane tag and counters."""
    import argparse

    parser = argparse.ArgumentParser(description="Emit a loop event (SPEC-NS-KIT-108).")
    sub = parser.add_subparsers(dest="command", required=True)
    lane = sub.add_parser("lane", help="record the lane tag and lane counters for one run")
    lane.add_argument("--nightshift-dir", default=".nightshift")
    lane.add_argument("--run-id", required=True)
    lane.add_argument("--spec-id", required=True)
    lane.add_argument("--lane", required=True)
    for field in LANE_COUNTER_FIELDS:
        lane.add_argument("--" + field.replace("_", "-"), required=True, type=_count_arg,
                          help="a non-negative number or 'unavailable'")
    lane.add_argument("--redispatch-reason", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        event = emit_lane_event(
            open_run_log(Path(args.nightshift_dir), args.run_id), args.spec_id, lane=args.lane,
            parent_tool_calls=args.parent_tool_calls, worker_wall_s=args.worker_wall_s,
            verifier_wall_s=args.verifier_wall_s, verifier_dispatches=args.verifier_dispatches,
            redispatch_reasons=args.redispatch_reason,
        )
    except ValueError as exc:
        print(f"Error: cannot record lane event: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(event, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
