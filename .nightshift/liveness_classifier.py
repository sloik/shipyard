"""Heartbeat-only liveness classification shared by Nightshift protocol tests.

The classifier deliberately consumes only a heartbeat's declared state and
age.  It never accepts file mtimes, branch movement, or commit counts as
liveness evidence.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
import re


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

    if entry.get("waiting_on") == "owner_approval":
        return "waiting_on_approval"

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
    if classification in {"stalled", "blocked", "waiting_on_approval"}:
        return classification
    if classification == "done":
        return "done"
    if not commit_made and not no_commit_expected:
        return "not_acting"
    return "done"


def sanitize_waiting_command(value: object) -> str:
    """Bound untrusted display text; never execute it or expose shell assignment values."""
    if not isinstance(value, str):
        return ""
    text = "".join(character for character in value if character.isprintable())
    text = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s;]+)",
                  lambda match: match.group().split("=", 1)[0] + "=[redacted]", text)
    return text[:200]


def waiting_age_min(value: object, *, now: datetime) -> float | None:
    """Use only an explicitly UTC waiting timestamp and the caller's clock."""
    if not isinstance(value, str):
        return None
    try:
        declared = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if declared.tzinfo is None or declared.utcoffset().total_seconds() != 0:
            return None
        current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        return max(0.0, (current - declared).total_seconds() / 60)
    except (ValueError, OverflowError):
        return None
