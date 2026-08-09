#!/usr/bin/env python3
"""
Append-only NDJSON event logging for Nightshift loop runs.
"""

from __future__ import annotations

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
