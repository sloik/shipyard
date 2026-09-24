"""Heartbeat-only liveness classification shared by Nightshift protocol tests.

The classifier deliberately consumes only a heartbeat's declared state and
age.  It never accepts file mtimes, branch movement, or commit counts as
liveness evidence.
"""

from collections.abc import Mapping


STALE_THRESHOLD_MIN = 20
TERMINAL_STATES = {
    "worker-done": "done",
    "worker-blocked": "blocked",
}


def classify_old(
    heartbeat_age_min: float,
    file_mtimes_changed_recently: bool,
    new_commit_since_start: bool,
) -> str:
    """Model the former, prohibited inferred-activity policy."""
    if heartbeat_age_min < STALE_THRESHOLD_MIN:
        return "ok"
    if file_mtimes_changed_recently:
        return "ok"
    if not new_commit_since_start:
        return "not_acting"
    return "ok"


def classify_heartbeat(entry: Mapping[str, object]) -> str:
    """Classify a heartbeat from its declared state, phase, and age only."""
    state = entry.get("heartbeat_state")
    if isinstance(state, str) and state in TERMINAL_STATES:
        return TERMINAL_STATES[state]

    age = float(entry["age_min"])
    phase = entry.get("phase")
    expected = entry.get("expected_duration_min")
    if isinstance(phase, str) and phase and expected is not None:
        return "ok" if age <= float(expected) else "stalled"
    return "ok" if age < STALE_THRESHOLD_MIN else "stalled"


def resolve_terminal(
    *, no_commit_expected: bool, commit_made: bool, classification: str
) -> str:
    """Resolve a non-stalled run without treating declared zero commits as failure."""
    if classification in {"stalled", "blocked"}:
        return classification
    if classification == "done":
        return "done"
    if not commit_made and not no_commit_expected:
        return "not_acting"
    return "done"
