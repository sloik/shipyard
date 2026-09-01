"""Artifact-side reachability sweeps for ``canonical/reports/`` and ``canonical/runs/``.

SPEC-252 established the shape: a validation surface driven only from the spec
side cannot see what the artifact side is missing, and closed that gap for
``canonical/release-handoffs/`` (see ``release_handoff.sweep_handoff_directory``).
SPEC-272 extends the same shape to the two remaining artifact directories.
Reports and runs are not identical to release handoffs -- entries are
directories as well as files, naming is conventional rather than declared, and
a run legitimately outlives its spec -- so each directory gets its own
reachability rule below, copied verbatim from SPEC-272's Decision section so
prose and code cannot drift silently (see ``tests/test_artifact_reachability.py``,
which reads that section directly).

Reports rule: an entry (file or directory) is reachable if its name contains a
``SPEC-<id>`` or ``BUG-<id>`` token and that ID names a spec that exists in the
corpus, in any status. An entry whose name contains tokens naming more than one
existing spec is ambiguous, not reachable. An entry with no such token is
reachable only if it matches one of two closed, recorded shapes: (a) a
session-level dated report, or (b) an explicit, closed allowlist of
project-level named docs. ``_wip/`` and ``failures/`` are excluded from the
sweep entirely, as are dotfiles (git bookkeeping such as ``.gitkeep``, never an
artifact). Anything else is unreachable.

Runs rule: an entry is reachable if its ``events.jsonl`` contains at least one
event whose ``spec_id`` names a spec that exists in the corpus, in any status.
Directory naming is never used as a reachability signal. A run directory with
no ``events.jsonl``, an empty/unparseable one, or one whose every ``spec_id``
names no spec in the corpus, is unreachable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable
from pathlib import Path

REPORTS_DIR = "reports"
RUNS_DIR = "runs"

# Structural, non-artifact entries excluded from the reports sweep entirely.
REPORTS_EXCLUDED_NAMES = frozenset({"_wip", "failures"})

# A SPEC-<id>/BUG-<id> token, greedy over hyphenated numeric suffixes so
# "SPEC-229-007" resolves as one token rather than "SPEC-229" plus a residual
# "-007" -- report/run entries can legitimately belong to a sub-spec ID.
# "SPEC-QUESTIONS-<NNN>" is a recognized non-numeric spec-ID shape (the
# report open-question sweep convention; SPEC-QUESTIONS-001/002 predate this
# module) and is matched explicitly rather than widened generically.
_SPEC_TOKEN_RE = re.compile(r"(?:SPEC-QUESTIONS-\d+|(?:SPEC|BUG)-\d+(?:-\d+)*)")

# Session-level dated report shape (Decision shape (a)): a bare or
# suffixed nightshift report, or a versioned nightshift release note.
_SESSION_REPORT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}-nightshift-report(-[A-Za-z0-9][\w.-]*)?\.md$"
    r"|^\d{4}-\d{2}-\d{2}-nightshift-release-\d+\.\d+\.\d+\.md$"
)

# Closed allowlist of project-level named docs (Decision shape (b)). Extend
# only by editing this list, never by pattern-matching. The "minimum" set is
# the one SPEC-272's prose names explicitly; the full set additionally
# includes their generated companion status files (same producer, same
# family -- see ``analyze_metrics.py``'s GAP-ANALYTICS.md/-STATUS.json and
# metrics-trend.md/REGRESSION-STATUS.json pairs), found during the R4 survey.
REPORTS_NAMED_DOC_ALLOWLIST_MINIMUM = frozenset(
    {"GAP-ANALYTICS.md", "metrics-trend.md", "pattern-health.md"}
)
REPORTS_NAMED_DOC_ALLOWLIST = REPORTS_NAMED_DOC_ALLOWLIST_MINIMUM | {
    "GAP-ANALYTICS-STATUS.json",
    "REGRESSION-STATUS.json",
}

# R4: the closed list of pre-existing entries that predate this sweep and
# cannot satisfy the reachability rule, each with its own reason. A newly
# introduced unreachable entry must be resolved (renamed/retired), never
# quietly added here -- see test_accepted_unreachable_list_is_closed.
REPORTS_ACCEPTED_UNREACHABLE: dict[str, str] = {
    "2026-04-11-spec019-context-fidelity.md": (
        "Predates the SPEC-\\d+ hyphenated naming convention (lowercase, no "
        "hyphen). Documents historical SPEC-019, whose spec file no longer "
        "exists in the specs/ corpus, so no rename can make it satisfy the "
        "any-status token-match rule. Kept for provenance rather than "
        "retired."
    ),
}

ORPHANED_REPORT_ERROR = (
    "orphaned report artifact: its name names no existing spec/bug id and "
    "matches neither the session-report nor named-doc shape, so nothing "
    "declares or validates it"
)
AMBIGUOUS_REPORT_ERROR = (
    "ambiguous report artifact: its name names more than one existing "
    "spec/bug id"
)
UNTRACKED_REPORT_ERROR = (
    "untracked report artifact: it is absent from committed content, so a "
    "working-tree measurement and a checkout disagree about the corpus"
)
ORPHANED_RUN_ERROR = (
    "orphaned run: events.jsonl is missing, empty, unparseable, or every "
    "spec_id in it names no existing spec"
)
UNTRACKED_RUN_ERROR = (
    "untracked run: it is absent from committed content, so a working-tree "
    "measurement and a checkout disagree about the corpus"
)


def _spec_token_matches(name: str, spec_ids: Collection[str]) -> set[str]:
    """Return the distinct existing spec/bug IDs whose token appears in name."""
    known = {str(spec_id) for spec_id in spec_ids}
    return {token for token in _SPEC_TOKEN_RE.findall(name) if token in known}


def report_reachability(name: str, spec_ids: Collection[str]) -> str:
    """Classify one ``reports/`` entry name as the Decision's reachability rule.

    Returns ``"reachable"``, ``"ambiguous"``, or ``"unreachable"``. Pure and
    dependency-free so it is directly testable against the spec's own Decision
    prose (AC1).
    """
    matches = _spec_token_matches(name, spec_ids)
    if len(matches) > 1:
        return "ambiguous"
    if len(matches) == 1:
        return "reachable"
    if _SESSION_REPORT_RE.match(name):
        return "reachable"
    if name in REPORTS_NAMED_DOC_ALLOWLIST:
        return "reachable"
    return "unreachable"


def run_reachability(events_path: Path, spec_ids: Collection[str]) -> bool:
    """Return whether ``events_path`` names at least one existing spec.

    Reads ``spec_id`` from each JSON line -- directory naming is never
    consulted, proving R1's "never inferred from directory naming" clause
    structurally (the caller never even passes a name in).
    """
    if not events_path.is_file():
        return False
    known = {str(spec_id) for spec_id in spec_ids}
    try:
        text = events_path.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        spec_id = event.get("spec_id")
        if spec_id is not None and str(spec_id) in known:
            return True
    return False


def _is_tracked(relative: str, is_dir: bool, tracked_paths: Collection[str]) -> bool:
    if not is_dir:
        return relative in tracked_paths
    prefix = relative + "/"
    return any(path.startswith(prefix) for path in tracked_paths)


def sweep_reports_directory(
    canonical: Path,
    spec_ids: Iterable[str],
    *,
    tracked_paths: Collection[str] | None = None,
) -> dict[str, list[str]]:
    """Judge ``canonical/reports/`` from the artifact side (R1/R2/R3).

    ``spec_ids`` is every spec ID in the corpus regardless of status, supplied
    by the caller so this module stays free of spec parsing. Pre-existing
    entries in ``REPORTS_ACCEPTED_UNREACHABLE`` are exempted from the orphan
    finding (R4) but still get their untracked check like any other entry.
    """
    directory = canonical / REPORTS_DIR
    if not directory.is_dir():
        return {}
    known_ids = list(spec_ids)
    findings: dict[str, list[str]] = {}
    for path in sorted(directory.iterdir()):
        name = path.name
        if name.startswith(".") or name in REPORTS_EXCLUDED_NAMES:
            continue
        relative = f"{REPORTS_DIR}/{name}"
        errors: list[str] = []
        outcome = report_reachability(name, known_ids)
        if outcome == "unreachable" and name not in REPORTS_ACCEPTED_UNREACHABLE:
            errors.append(f"{relative}: {ORPHANED_REPORT_ERROR}")
        elif outcome == "ambiguous":
            matches = sorted(_spec_token_matches(name, known_ids))
            errors.append(
                f"{relative}: {AMBIGUOUS_REPORT_ERROR} ({', '.join(matches)})"
            )
        if tracked_paths is not None and not _is_tracked(
            relative, path.is_dir(), tracked_paths
        ):
            errors.append(f"{relative}: {UNTRACKED_REPORT_ERROR}")
        if errors:
            findings[relative] = errors
    return findings


def sweep_runs_directory(
    canonical: Path,
    spec_ids: Iterable[str],
    *,
    tracked_paths: Collection[str] | None = None,
) -> dict[str, list[str]]:
    """Judge ``canonical/runs/`` from the artifact side (R1/R2/R3)."""
    directory = canonical / RUNS_DIR
    if not directory.is_dir():
        return {}
    known_ids = list(spec_ids)
    findings: dict[str, list[str]] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_dir():
            continue
        relative = f"{RUNS_DIR}/{path.name}"
        errors: list[str] = []
        if not run_reachability(path / "events.jsonl", known_ids):
            errors.append(f"{relative}: {ORPHANED_RUN_ERROR}")
        if tracked_paths is not None and not _is_tracked(relative, True, tracked_paths):
            errors.append(f"{relative}: {UNTRACKED_RUN_ERROR}")
        if errors:
            findings[relative] = errors
    return findings
