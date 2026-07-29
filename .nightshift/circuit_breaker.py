#!/usr/bin/env python3
"""
Concrete circuit breaker for Nightshift specs.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from failure_persistence import _atomic_write_text, persist_failure


SignalLiteral = Literal[
    "spec_start",
    "build_error",
    "test_regression",
    "review_cycle",
    "phase_end",
]


@dataclass(frozen=True)
class StallEvent:
    signal: SignalLiteral
    timestamp: datetime
    error_fingerprint: str = ""
    attempt_number: int = 0
    pass_rate: float = 0.0
    phase_name: str = ""
    duration_s: int = 0
    attempt_description: str = ""


@dataclass(frozen=True)
class TriggerResult:
    signal: str
    threshold_value: float
    observed_value: float
    blocked_report_path: Path
    attempts_file_path: Path
    failure_ledger_path: Path
    spec_update: str
    message: str


def _as_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _format_stamp(timestamp: datetime) -> str:
    return _as_utc(timestamp).strftime("%Y%m%dT%H%M%SZ")


def _format_iso(timestamp: datetime) -> str:
    return _as_utc(timestamp).isoformat().replace("+00:00", "Z")


def _snapshot_timestamp(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return _format_iso(value)


def _restore_timestamp(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class CircuitBreaker:
    def __init__(
        self,
        project_root: Path,
        spec_id: str,
        spec_file: str,
        config: Dict[str, Any],
        phase_history: Dict[str, list[int]],
        event_log=None,
    ):
        self._project_root = Path(project_root)
        self._spec_id = spec_id
        self._spec_file = spec_file
        self._config = self._validate_config(config)
        self._event_log = event_log

        self._spec_start_timestamp: Optional[datetime] = None
        self._latest_timestamp: Optional[datetime] = None

        self._last_error_fingerprint: Optional[str] = None
        self._error_streaks: Dict[str, int] = {}
        self._review_cycles = 0

        self._phase_samples: Dict[str, list[int]] = {}
        for phase_name, durations in phase_history.items():
            self._phase_samples[str(phase_name)] = [int(value) for value in durations]

        self._last_test_pass_rate: Optional[float] = None
        self._test_regression_streak = 0
        self._attempt_log: list[str] = []

        self._triggered = False
        self._trigger_result: Optional[TriggerResult] = None

    @staticmethod
    def _validate_config(config: Dict[str, Any]) -> Dict[str, float]:
        if not isinstance(config, dict):
            raise ValueError("circuit breaker config must be a dict")

        validated: Dict[str, float] = {}
        required = {
            "max_same_error": int,
            "max_review_cycles": int,
            "max_spec_duration_min": (int, float),
            "phase_duration_multiplier": (int, float),
        }
        for key, expected_type in required.items():
            if key not in config:
                raise ValueError(f"missing circuit breaker config value: {key}")
            value = config[key]
            if isinstance(value, bool) or not isinstance(value, expected_type):
                raise ValueError(
                    f"invalid circuit breaker config value for {key}: {value!r}"
                )
            validated[key] = float(value)
        return validated

    def record_event(self, event: StallEvent) -> Optional[TriggerResult]:
        if self._triggered:
            return self._trigger_result

        event_timestamp = _as_utc(event.timestamp)
        self._latest_timestamp = event_timestamp
        self._append_attempt(event)

        if event.signal == "spec_start":
            self._spec_start_timestamp = event_timestamp
        elif event.signal == "build_error":
            result = self._handle_build_error(event)
            if result is not None:
                return result
        elif event.signal == "review_cycle":
            self._review_cycles += 1
            if self._review_cycles > self._config["max_review_cycles"]:
                return self._trigger(
                    signal="review_cycle",
                    threshold_value=self._config["max_review_cycles"],
                    observed_value=float(self._review_cycles),
                    event=event,
                )
        elif event.signal == "phase_end":
            result = self._handle_phase_end(event)
            if result is not None:
                return result
        elif event.signal == "test_regression":
            result = self._handle_test_regression(event)
            if result is not None:
                return result

        elapsed_result = self._check_elapsed_time(event)
        if elapsed_result is not None:
            return elapsed_result

        return None

    def _append_attempt(self, event: StallEvent) -> None:
        if event.signal == "spec_start":
            return

        description = event.attempt_description.strip()
        if not description:
            description = self._default_attempt_description(event)
        self._attempt_log.append(description)

    def _default_attempt_description(self, event: StallEvent) -> str:
        if event.signal == "build_error":
            return f"Build error fingerprint={event.error_fingerprint or 'unknown'}"
        if event.signal == "review_cycle":
            return f"Review cycle {self._review_cycles + 1}"
        if event.signal == "test_regression":
            return f"Test regression pass_rate={event.pass_rate}"
        if event.signal == "phase_end":
            return f"Phase {event.phase_name or 'unknown'} duration={event.duration_s}s"
        return event.signal

    def _handle_build_error(self, event: StallEvent) -> Optional[TriggerResult]:
        fingerprint = event.error_fingerprint
        if fingerprint != self._last_error_fingerprint:
            self._error_streaks = {}
            self._error_streaks[fingerprint] = 1
            self._last_error_fingerprint = fingerprint
        else:
            self._error_streaks[fingerprint] = self._error_streaks.get(fingerprint, 0) + 1

        streak = self._error_streaks.get(fingerprint, 0)
        if streak >= self._config["max_same_error"]:
            return self._trigger(
                signal="build_error",
                threshold_value=self._config["max_same_error"],
                observed_value=float(streak),
                event=event,
            )
        return None

    def _handle_phase_end(self, event: StallEvent) -> Optional[TriggerResult]:
        phase_name = event.phase_name
        prior_samples = list(self._phase_samples.get(phase_name, []))
        result = None
        if len(prior_samples) >= 2:
            running_avg = sum(prior_samples) / len(prior_samples)
            threshold = running_avg * self._config["phase_duration_multiplier"]
            if event.duration_s > threshold:
                result = self._trigger(
                    signal="phase_end",
                    threshold_value=threshold,
                    observed_value=float(event.duration_s),
                    event=event,
                )

        self._phase_samples.setdefault(phase_name, []).append(int(event.duration_s))
        return result

    def _handle_test_regression(self, event: StallEvent) -> Optional[TriggerResult]:
        pass_rate = float(event.pass_rate)
        if self._last_test_pass_rate is None or pass_rate > self._last_test_pass_rate:
            self._test_regression_streak = 1
        else:
            self._test_regression_streak += 1
        self._last_test_pass_rate = pass_rate

        if self._test_regression_streak >= 3:
            return self._trigger(
                signal="test_regression",
                threshold_value=3,
                observed_value=float(self._test_regression_streak),
                event=event,
            )
        return None

    def _check_elapsed_time(self, event: StallEvent) -> Optional[TriggerResult]:
        if self._spec_start_timestamp is None:
            return None

        elapsed = self.elapsed_minutes()
        if elapsed >= self._config["max_spec_duration_min"]:
            return self._trigger(
                signal="elapsed_time",
                threshold_value=self._config["max_spec_duration_min"],
                observed_value=elapsed,
                event=event,
            )
        return None

    def _trigger(
        self,
        signal: str,
        threshold_value: float,
        observed_value: float,
        event: StallEvent,
    ) -> TriggerResult:
        timestamp = _as_utc(event.timestamp)
        if self._event_log is not None:
            self._event_log.emit(
                "stall_detected",
                spec_id=self._spec_id,
                ts=_format_iso(timestamp),
                signal=signal,
                threshold_value=threshold_value,
                observed_value=observed_value,
            )

        blocked_report_path = self._project_root / "reports" / (
            f"BLOCKED-{self._spec_id}-{_format_stamp(timestamp)}.md"
        )
        attempts_file_path = self._project_root / "knowledge" / "attempts" / (
            f"{self._spec_id}-circuit-breaker-{_format_stamp(timestamp)}.md"
        )

        _atomic_write_text(blocked_report_path, self._build_blocked_report(signal, event))
        _atomic_write_text(attempts_file_path, self._build_attempts_file(signal, event))

        description = (
            f"Circuit breaker: {signal} threshold={threshold_value} "
            f"observed={observed_value}"
        )
        persisted = persist_failure(
            project_root=self._project_root,
            source_file="circuit_breaker.py",
            error_type=f"circuit_breaker:{signal}",
            description=description,
            details={
                "signal": signal,
                "threshold": threshold_value,
                "observed": observed_value,
                "state_snapshot": self.get_state_snapshot(),
            },
            spec_file=self._spec_file,
            status="blocked",
        )

        trigger_result = TriggerResult(
            signal=signal,
            threshold_value=threshold_value,
            observed_value=observed_value,
            blocked_report_path=blocked_report_path,
            attempts_file_path=attempts_file_path,
            failure_ledger_path=Path(persisted["ledger_path"]),
            spec_update=persisted["spec_update"],
            message=description,
        )
        self._triggered = True
        self._trigger_result = trigger_result

        if self._event_log is not None:
            self._event_log.emit(
                "circuit_breaker_triggered",
                spec_id=self._spec_id,
                ts=_format_iso(timestamp),
                signal=signal,
                threshold_value=threshold_value,
                observed_value=observed_value,
                blocked_report_path=str(blocked_report_path),
                attempts_file_path=str(attempts_file_path),
            )

        return trigger_result

    def _build_blocked_report(self, signal: str, event: StallEvent) -> str:
        phase = event.phase_name or event.signal
        attempts = "\n".join(f"- Attempt {idx}: {text}" for idx, text in enumerate(self._attempt_log, start=1))
        if not attempts:
            attempts = "- Attempt 1: No attempt details captured."

        return (
            f"# Blocked: {self._spec_id}\n\n"
            f"**When:** {_format_iso(event.timestamp)}\n"
            f"**Phase:** {phase}\n"
            f"**Signal:** {signal}\n"
            f"**Failure class:** circuit_breaker:{signal}\n\n"
            "## What Was Attempted\n"
            f"{attempts}\n\n"
            "## Root Cause Hypothesis\n"
            f"Circuit breaker detected a stall via `{signal}` and stopped the spec to avoid unproductive retry loops.\n\n"
            "## What a Human Needs to Do\n"
            "Review the blocked report, inspect the latest failure context, and decide whether the spec, environment, or implementation plan needs to change.\n"
        )

    def _build_attempts_file(self, signal: str, event: StallEvent) -> str:
        date_value = _as_utc(event.timestamp).strftime("%Y-%m-%d")
        approach = f"Circuit breaker triggered by {signal}"
        return (
            "---\n"
            f'spec_id: "{self._spec_id}"\n'
            'problem_area: "stall"\n'
            f'date: "{date_value}"\n'
            'status: "blocked"\n'
            f'approach: "{approach}"\n'
            'model_used: ""\n'
            f'phase: "{event.phase_name or event.signal}"\n'
            f'error_type: "circuit_breaker:{signal}"\n'
            "---\n\n"
            f"# {self._spec_id}: [Circuit breaker stall] — [{approach}]\n\n"
            f"**Spec:** {self._spec_id}\n"
            f"**Date:** {date_value}\n"
            "**Status:** blocked\n"
            "**Problem area:** stall\n\n"
            "Status: blocked\n\n"
            "## What Was Tried\n\n"
            "Circuit breaker captured repeated failed attempts during this spec run.\n\n"
            "## Why It Failed\n\n"
            f"Triggered stall signal `{signal}` after threshold evaluation stopped further work.\n\n"
            "## What We Learned\n\n"
            "[placeholder]\n\n"
            "## Revisit If\n\n"
            "[placeholder]\n\n"
            "## Related Patterns\n\n"
            "- (none)\n"
        )

    def error_streak(self, fingerprint: str) -> int:
        return self._error_streaks.get(fingerprint, 0)

    def review_cycle_count(self) -> int:
        return self._review_cycles

    def elapsed_minutes(self) -> float:
        if self._spec_start_timestamp is None or self._latest_timestamp is None:
            return 0.0
        return (
            (_as_utc(self._latest_timestamp) - _as_utc(self._spec_start_timestamp)).total_seconds()
            / 60.0
        )

    def is_triggered(self) -> bool:
        return self._triggered

    def get_state_snapshot(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "spec_start_timestamp": _snapshot_timestamp(self._spec_start_timestamp),
            "latest_timestamp": _snapshot_timestamp(self._latest_timestamp),
            "last_error_fingerprint": self._last_error_fingerprint,
            "error_streaks": dict(self._error_streaks),
            "review_cycles": self._review_cycles,
            "phase_samples": {key: list(values) for key, values in self._phase_samples.items()},
            "last_test_pass_rate": self._last_test_pass_rate,
            "test_regression_streak": self._test_regression_streak,
            "attempt_log": list(self._attempt_log),
            "triggered": self._triggered,
            "trigger_result": None,
        }
        if self._trigger_result is not None:
            trigger_result = asdict(self._trigger_result)
            trigger_result["blocked_report_path"] = str(self._trigger_result.blocked_report_path)
            trigger_result["attempts_file_path"] = str(self._trigger_result.attempts_file_path)
            trigger_result["failure_ledger_path"] = str(self._trigger_result.failure_ledger_path)
            snapshot["trigger_result"] = trigger_result
        return snapshot

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Dict[str, Any],
        project_root: Path,
        spec_id: str,
        spec_file: str,
        config: Dict[str, Any],
        phase_history: Dict[str, list[int]],
    ) -> "CircuitBreaker":
        breaker = cls(
            project_root=project_root,
            spec_id=spec_id,
            spec_file=spec_file,
            config=config,
            phase_history=phase_history,
        )
        breaker._spec_start_timestamp = _restore_timestamp(snapshot.get("spec_start_timestamp"))
        breaker._latest_timestamp = _restore_timestamp(snapshot.get("latest_timestamp"))
        breaker._last_error_fingerprint = snapshot.get("last_error_fingerprint")
        breaker._error_streaks = {
            str(key): int(value) for key, value in snapshot.get("error_streaks", {}).items()
        }
        breaker._review_cycles = int(snapshot.get("review_cycles", 0))
        breaker._phase_samples = {
            str(key): [int(item) for item in values]
            for key, values in snapshot.get("phase_samples", {}).items()
        }
        breaker._last_test_pass_rate = snapshot.get("last_test_pass_rate")
        if breaker._last_test_pass_rate is not None:
            breaker._last_test_pass_rate = float(breaker._last_test_pass_rate)
        breaker._test_regression_streak = int(snapshot.get("test_regression_streak", 0))
        breaker._attempt_log = [str(item) for item in snapshot.get("attempt_log", [])]
        breaker._triggered = bool(snapshot.get("triggered", False))

        trigger_result = snapshot.get("trigger_result")
        if trigger_result is not None:
            breaker._trigger_result = TriggerResult(
                signal=str(trigger_result["signal"]),
                threshold_value=float(trigger_result["threshold_value"]),
                observed_value=float(trigger_result["observed_value"]),
                blocked_report_path=Path(trigger_result["blocked_report_path"]),
                attempts_file_path=Path(trigger_result["attempts_file_path"]),
                failure_ledger_path=Path(trigger_result["failure_ledger_path"]),
                spec_update=str(trigger_result["spec_update"]),
                message=str(trigger_result["message"]),
            )

        return breaker
