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


ACTIVITY_CATEGORIES = ('reasoning', 'human_work', 'tool', 'tests', 'scripts', 'waiting')


def format_activity_duration(seconds: float | None) -> str:
    if seconds is None:
        return 'unknown'
    minutes = int(max(0, seconds) // 60)
    if seconds and not minutes:
        return '<1m'
    if minutes < 60:
        return f'{minutes}m'
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f'{hours}h {minutes}m'
    days, hours = divmod(hours, 24)
    return f'{days}d {hours}h {minutes}m'


def _activity_epoch(value):
    parsed = parse_timestamp(value)
    return parsed.timestamp() if parsed is not None and parsed.tzinfo is not None else None


def _activity_union(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def project_activity(spec_id: str, checkpoints: list[dict], events: list[dict], *, now=None) -> dict:
    """Pure projection of explicit reliable boundaries; no Git, mtime or liveness inference."""
    from datetime import timezone
    now = now or datetime.now(timezone.utc)
    observed = now.timestamp()
    history = [row for row in checkpoints if row.get('spec_id') == spec_id]
    progress, opened, previous = [], None, None
    incomplete = not history
    unknown_progress = False
    for row in history:
        status = row.get('status')
        if status == previous:
            continue
        timestamp = _activity_epoch(row.get('created_at'))
        if timestamp is None or timestamp > observed:
            incomplete = True
            unknown_progress |= status == 'in_progress' or opened is not None
            opened = None
        else:
            if opened is not None:
                if timestamp >= opened:
                    progress.append((opened, timestamp))
                else:
                    incomplete = True
                opened = None
            if status == 'in_progress':
                opened = timestamp
        previous = status
    if opened is not None:
        progress.append((opened, observed))
    progress = _activity_union(progress)
    # First surviving checkpoint does not establish the lifetime before it.
    incomplete |= bool(history and history[0].get('status') not in ('draft', 'planned', 'ready'))
    elapsed = sum(end - start for start, end in progress) if progress or (history and not unknown_progress) else None
    categories = {key: [] for key in ACTIVITY_CATEGORIES}
    episodes, seen = {}, set()
    unreliable = False
    valid_events = []
    for event in events:
        identity = (event.get('spec_id'), event.get('run_id'), event.get('event_id'))
        if event.get('spec_id') != spec_id or identity in seen:
            continue
        seen.add(identity)
        timestamp = _activity_epoch(event.get('at'))
        if timestamp is None or timestamp > observed or not event.get('run_id') or not event.get('episode_id'):
            unreliable = True
            continue
        category = event.get('category')
        if category not in (*ACTIVITY_CATEGORIES, 'discussion'):
            unreliable = True
            continue
        episodes.setdefault((event['run_id'], event['episode_id'], category), []).append((timestamp, event))
        valid_events.append((timestamp, event))
    discussions = []
    waiting_episodes = []
    for (run_id, episode_id, category), boundaries in episodes.items():
        boundaries.sort(key=lambda pair: pair[0])
        if category == 'discussion':
            first, wait_start, wait_event, takeover = None, None, None, None
            answers = []
            for timestamp, event in boundaries:
                kind = event.get('kind')
                if kind == 'question':
                    if takeover is not None:
                        unreliable = True
                        continue
                    if first is None:
                        first = timestamp
                    if wait_start is None:
                        wait_start, wait_event = timestamp, event
                elif kind == 'answer':
                    if first is None or takeover is not None:
                        unreliable = True
                        continue
                    answers.append(event['at'])
                    if wait_start is not None:
                        categories['waiting'].append((wait_start, timestamp))
                        wait_start = None
                elif kind == 'takeover' and first is not None and takeover is None:
                    takeover = timestamp
                    if wait_start is not None:
                        categories['waiting'].append((wait_start, timestamp))
                        wait_start = None
            if first is not None:
                categories['human_work'].append((first, takeover if takeover is not None else observed))
                if wait_start is not None:
                    categories['waiting'].append((wait_start, observed))
                    waiting_episodes.append((wait_start, wait_event))
                discussions.append({'episode_id': episode_id, 'run_id': run_id, 'start': first,
                    'answer_arrivals': answers, 'takeover': datetime.fromtimestamp(takeover, timezone.utc).isoformat() if takeover is not None else None,
                    'open': takeover is None, 'approximate': True,
                    'duration_seconds': (takeover if takeover is not None else observed) - first})
            continue
        starts = [(at, event) for at, event in boundaries if event.get('kind') == 'start']
        ends = [at for at, event in boundaries if event.get('kind') == 'end']
        if len(starts) != 1 or len(ends) > 1 or (ends and ends[0] < starts[0][0]):
            unreliable = True
            continue
        if ends:
            categories[category].append((starts[0][0], ends[0]))
        elif category == 'waiting':
            categories[category].append((starts[0][0], observed))
            waiting_episodes.append(starts[0])
        else:
            unreliable = True  # A missing execution closure is not proof of continuous execution.
    categories = {key: _activity_union(value) for key, value in categories.items()}
    union = _activity_union([interval for values in categories.values() for interval in values])
    covered = sum(max(0, min(end, stop) - max(start, begin)) for start, end in progress for begin, stop in union)
    edges = {}
    for values in categories.values():
        for start, end in values:
            edges[start] = edges.get(start, 0) + 1
            edges[end] = edges.get(end, 0) - 1
    active, prior, overlap = 0, None, 0
    for edge, delta in sorted(edges.items()):
        if prior is not None and active >= 2:
            overlap += edge - prior
        active += delta
        prior = edge
    current_run = history[-1].get('run_id') if history else None
    current_events = [(at, event) for at, event in valid_events if current_run is None or event['run_id'] == current_run]
    last = max(current_events, key=lambda pair: pair[0])[1] if current_events else {}
    current_waits = [(at, event) for at, event in waiting_episodes if current_run is None or event['run_id'] == current_run]
    wait = max(current_waits, key=lambda pair: pair[0])[1] if current_waits else None
    discussion_pending = any(item['open'] and (current_run is None or item['run_id'] == current_run) for item in discussions)
    actor = (wait or last).get('actor')
    phase = (wait or last).get('phase') or ('awaiting_human' if wait else 'awaiting_agent_takeover' if discussion_pending else last.get('category') or 'unrecorded')
    if discussion_pending and not wait:
        actor = 'agent:parent'
    totals = {key: sum(end - start for start, end in values) for key, values in categories.items()}
    return {'spec_id': spec_id, 'observed_at': now.isoformat(), 'in_progress_seconds': elapsed,
            'in_progress_label': format_activity_duration(elapsed), 'known_subtotal': True,
            'status_history_available': bool(history), 'history_incomplete': bool(incomplete), 'history_coverage': 'Recorded checkpoints only; earlier unrecorded history unknown.',
            'category_seconds': totals, 'category_labels': {key: format_activity_duration(value) for key, value in totals.items()},
            'covered_in_progress_seconds': covered if elapsed is not None else None,
            'unclassified_seconds': max(0, elapsed - covered) if elapsed is not None else None,
            'unclassified_label': format_activity_duration(max(0, elapsed - covered) if elapsed is not None else None),
            'overlap_label': format_activity_duration(overlap),
            'overlap_seconds': overlap, 'human_work_is_estimate': bool(discussions),
            'human_work_note': 'Approximate discussion involvement; not continuous active human effort.' if discussions else None,
            'incomplete_activity': unreliable, 'current_phase': phase, 'actor': actor,
            'waiting': wait is not None, 'required_action': wait.get('required_action') if wait else None,
            'next_action': (wait or last).get('next_action'), 'last_heartbeat': 'unknown',
            'discussion_episode_count': len(discussions), 'discussions': discussions[-20:]}
