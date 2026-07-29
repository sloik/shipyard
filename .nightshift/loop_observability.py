#!/usr/bin/env python3
"""Loop observability metrics over Nightshift execution history.

Computes DevOps-style loop health from the existing history DB:
MTTD, MTTR, CFR, and format-failure rates.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional


FAILURE_STATUSES = {"failed", "blocked", "discarded", "partial"}
FAILURE_SIGNAL_EVENTS = {
    "agent_output_invalid",
    "build_failed",
    "handler_outcome_received",
    "invalid_json",
    "output_schema_invalid",
    "review_rejected",
    "schema_invalid",
    "spec_failed",
    "test_failed",
    "validation_failed",
}
DETECTION_EVENTS = {
    "circuit_breaker_fired",
    "failure_classified",
    "rollback_completed",
    "rollback_started",
    "spec_blocked",
    "spec_escalated",
    "spec_failed",
    "spec_rolled_back",
}
RECOVERY_EVENTS = {
    "rerun_succeeded",
    "run_completed",
    "spec_completed",
    "spec_done",
    "spec_unblocked",
    "status_done",
}
ROLLBACK_EVENTS = {"rollback_completed", "rollback_started", "spec_rolled_back"}
FOLLOWUP_EVENTS = {"followup_fix_required", "follow_up_fix_required"}
FORMAT_FAILURE_EVENTS = {"agent_output_invalid", "invalid_json", "output_schema_invalid", "schema_invalid"}
FORMAT_FAILURE_ERROR_TYPES = {"invalid_json", "json_decode_error", "schema_invalid", "output_schema_invalid"}


@dataclass(frozen=True)
class HistoryEvent:
    run_id: str
    event_type: str
    timestamp: str
    spec_id: Optional[str]
    data: dict[str, Any]

    @property
    def dt(self) -> Optional[datetime]:
        return parse_timestamp(self.timestamp)


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def pct(num: int, denom: int) -> Optional[float]:
    return round(100.0 * num / denom, 1) if denom else None


def mean_seconds(values: Iterable[float]) -> Optional[float]:
    items = list(values)
    return round(sum(items) / len(items), 1) if items else None


def _event_payload(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["data_json"]
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_events(conn: sqlite3.Connection) -> dict[str, list[HistoryEvent]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT run_id, spec_id, event_type, timestamp, data_json "
        "FROM events ORDER BY timestamp ASC, id ASC"
    ).fetchall()
    by_run: dict[str, list[HistoryEvent]] = {}
    for row in rows:
        event = HistoryEvent(
            run_id=row["run_id"],
            event_type=str(row["event_type"] or ""),
            timestamp=str(row["timestamp"] or ""),
            spec_id=row["spec_id"],
            data=_event_payload(row),
        )
        by_run.setdefault(event.run_id, []).append(event)
    return by_run


def _is_failure_signal(event: HistoryEvent) -> bool:
    if event.event_type in FAILURE_SIGNAL_EVENTS:
        if event.event_type == "handler_outcome_received":
            outcome = str(event.data.get("outcome") or event.data.get("status") or "").lower()
            return outcome not in {"", "ok", "pass", "passed", "success", "completed"}
        return True
    if str(event.data.get("error_type") or "").lower() in FORMAT_FAILURE_ERROR_TYPES:
        return True
    return False


def _is_detection(event: HistoryEvent) -> bool:
    if event.event_type in DETECTION_EVENTS:
        return True
    if event.event_type == "retry_decided":
        action = str(event.data.get("action") or "").upper()
        return action in {"ABORT", "BLOCK", "ESCALATE"}
    return False


def _is_recovery(event: HistoryEvent) -> bool:
    if event.event_type not in RECOVERY_EVENTS:
        return False
    if event.event_type == "run_completed":
        outcome = str(event.data.get("outcome") or event.data.get("status") or "").lower()
        return outcome in {"", "completed", "done", "success"}
    return True


def _is_format_failure(event: HistoryEvent) -> bool:
    return (
        event.event_type in FORMAT_FAILURE_EVENTS
        or str(event.data.get("error_type") or "").lower() in FORMAT_FAILURE_ERROR_TYPES
    )


def _is_easy_fix(event: HistoryEvent) -> bool:
    if event.data.get("easy_fix") is True:
        return True
    value = str(
        event.data.get("fix_difficulty")
        or event.data.get("recovery")
        or event.data.get("repair")
        or ""
    ).lower()
    return value in {"easy", "trivial", "mechanical", "auto", "automatic"}


def _requires_change_fix(statuses: list[str], events: list[HistoryEvent]) -> bool:
    if any(status in FAILURE_STATUSES for status in statuses):
        return True
    for event in events:
        if event.event_type in ROLLBACK_EVENTS or event.event_type in FOLLOWUP_EVENTS:
            return True
        if event.data.get("rollback") is True or event.data.get("followup_fix_required") is True:
            return True
    return False


def compute_from_connection(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute loop observability metrics from an open history DB connection."""
    conn.row_factory = sqlite3.Row
    runs = conn.execute("SELECT run_id, outcome FROM runs").fetchall()
    run_ids = [str(row["run_id"]) for row in runs]
    by_run = _load_events(conn)

    status_rows = conn.execute("SELECT run_id, status, error_type FROM spec_results").fetchall()
    statuses_by_run: dict[str, list[str]] = {run_id: [] for run_id in run_ids}
    format_failure_run_ids: set[str] = set()
    easy_fix_run_ids: set[str] = set()
    for row in status_rows:
        statuses_by_run.setdefault(str(row["run_id"]), []).append(str(row["status"] or ""))
        if str(row["error_type"] or "").lower() in FORMAT_FAILURE_ERROR_TYPES:
            format_failure_run_ids.add(str(row["run_id"]))

    mttd_values: list[float] = []
    mttr_values: list[float] = []
    for run_id in run_ids:
        events = by_run.get(run_id, [])
        first_failure = next((event for event in events if _is_failure_signal(event) and event.dt), None)
        detection = None
        if first_failure and first_failure.dt:
            detection = next(
                (
                    event
                    for event in events
                    if _is_detection(event) and event.dt and event.dt >= first_failure.dt
                ),
                None,
            )
            if detection and detection.dt:
                mttd_values.append((detection.dt - first_failure.dt).total_seconds())
                recovery = next(
                    (
                        event
                        for event in events
                        if _is_recovery(event) and event.dt and event.dt >= detection.dt
                    ),
                    None,
                )
                if recovery and recovery.dt:
                    mttr_values.append((recovery.dt - detection.dt).total_seconds())

        for event in events:
            if _is_format_failure(event):
                format_failure_run_ids.add(run_id)
                if _is_easy_fix(event):
                    easy_fix_run_ids.add(run_id)

    failed_runs = sum(
        1
        for run_id in run_ids
        if _requires_change_fix(statuses_by_run.get(run_id, []), by_run.get(run_id, []))
    )
    total_runs = len(run_ids)
    total_format_failures = len(format_failure_run_ids)
    easy_format_failures = len(easy_fix_run_ids & format_failure_run_ids)

    return {
        "run_count": total_runs,
        "mttd_seconds": mean_seconds(mttd_values),
        "mttd_samples": len(mttd_values),
        "mttr_seconds": mean_seconds(mttr_values),
        "mttr_samples": len(mttr_values),
        "change_failure_rate": pct(failed_runs, total_runs),
        "change_failure_runs": failed_runs,
        "format_failure_rate": pct(total_format_failures, total_runs),
        "format_failure_count": total_format_failures,
        "format_failure_easy_fix_fraction": pct(easy_format_failures, total_format_failures),
        "format_failure_easy_fix_count": easy_format_failures,
    }


def compute_from_db(db_dir: Optional[Path] = None) -> dict[str, Any]:
    """Compute metrics from ``history.db`` under db_dir or ~/.nightshift."""
    root = Path(db_dir) if db_dir is not None else Path.home() / ".nightshift"
    db_path = root / "history.db"
    if not db_path.exists():
        return {
            "run_count": 0,
            "mttd_seconds": None,
            "mttd_samples": 0,
            "mttr_seconds": None,
            "mttr_samples": 0,
            "change_failure_rate": None,
            "change_failure_runs": 0,
            "format_failure_rate": None,
            "format_failure_count": 0,
            "format_failure_easy_fix_fraction": None,
            "format_failure_easy_fix_count": 0,
        }
    conn = sqlite3.connect(str(db_path))
    try:
        return compute_from_connection(conn)
    finally:
        conn.close()
