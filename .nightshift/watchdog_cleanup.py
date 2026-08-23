"""Classify parent-owned kickoff watchdog cleanup evidence (SPEC-226).

The parent agent owns harness operations such as stopping and listing background
tasks. This module does not invent a harness adapter; it makes the portable
classification and evidence fields testable once a parent supplies its observed
task ID and task listing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping


CHECKED_CLEAN = "checked-clean"
CHECK_FAILED = "check-failed"
CHECK_NOT_RUN = "check-not-run"
VALID_RESULTS = frozenset({CHECKED_CLEAN, CHECK_FAILED, CHECK_NOT_RUN})


@dataclass(frozen=True)
class WatchdogCleanupEvidence:
    """Portable, report-ready outcome for one parent terminal resolution."""

    result: str
    watchdog_task_id: str | None
    running_task_ids: tuple[str, ...]
    reason: str | None
    human_action_needed: bool

    def as_report_fields(self) -> dict[str, object]:
        return asdict(self)


def _task_id(task: object) -> str | None:
    if isinstance(task, str):
        return task.strip() or None
    if isinstance(task, Mapping):
        for key in ("task_id", "id"):
            value = task.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def classify_watchdog_cleanup(
    watchdog_task_id: str | None,
    running_tasks: Iterable[object] | None,
    *,
    stop_succeeded: bool | None,
    not_run_reason: str | None = None,
) -> WatchdogCleanupEvidence:
    """Return a controlled cleanup state without treating missing data as clean."""

    task_id = watchdog_task_id.strip() if isinstance(watchdog_task_id, str) else ""
    if not task_id:
        return WatchdogCleanupEvidence(
            CHECK_NOT_RUN, None, (), not_run_reason or "no watchdog was armed", False
        )
    if running_tasks is None:
        return WatchdogCleanupEvidence(
            CHECK_NOT_RUN,
            task_id,
            (),
            not_run_reason or "parent task listing unavailable",
            True,
        )

    running_ids = tuple(sorted({value for task in running_tasks if (value := _task_id(task))}))
    if stop_succeeded is not True:
        return WatchdogCleanupEvidence(
            CHECK_FAILED,
            task_id,
            running_ids,
            "watchdog stop failed or was not confirmed",
            True,
        )
    if task_id in running_ids:
        return WatchdogCleanupEvidence(
            CHECK_FAILED,
            task_id,
            running_ids,
            "watchdog task remains armed after stop",
            True,
        )
    return WatchdogCleanupEvidence(CHECKED_CLEAN, task_id, running_ids, None, False)
