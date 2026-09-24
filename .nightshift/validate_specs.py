#!/usr/bin/env python3
"""
Nightshift Spec Frontmatter Validator

Validates that spec .md files in a Nightshift specs/ directory have well-formed
frontmatter and use only canonical lifecycle status values.

Exit codes:
  0 — All validated files pass
  1 — One or more files have validation errors

Usage:
  python3 validate_specs.py <file_or_directory> [--format json|text]
"""

import json
import re
import subprocess
import tempfile
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True

from dependency_registry import DependencyRegistryResolver
from deployment_tiers import deployment_block_findings, resolve_deployment_policy
from lifecycle import migrate_legacy_planning, validate_blocked
import lifecycle
import spec_artifacts

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

import artifact_reachability
import release_handoff

try:
    from experiment_protocol import ExperimentProtocolError, load_descriptor
except ImportError:  # portable older project kit
    ExperimentProtocolError = ValueError
    load_descriptor = None

try:
    from spec_frontmatter import VALID_SPEC_STATUSES
    from spec_frontmatter import (
        NFR_FAMILY_STATUSES,
        FrontmatterError,
        parse_spec_file,
        status_error_for_spec,
        check_column_override as _check_column_override,
        is_nfr_family,
        nfr_is_bound_or_waived,
        nfr_match_reasons,
        PROMOTION_GAP_KINDS,
        promotion_gap_summary,
    )
except ImportError:
    # Fallback when run outside the canonical package (e.g. from a project's
    # .nightshift/ copy without spec_frontmatter.py on the path).
    VALID_SPEC_STATUSES = frozenset({
        "draft", "planned", "ready", "in_progress", "blocked", "done", "superseded",
        "active", "retired",   # type: nfr specs only
    })
    NFR_FAMILY_STATUSES = frozenset({"active", "retired"})
    _VALID_COLUMN_STATES_FB = frozenset({"expanded", "collapsed", "hidden"})

    class FrontmatterError(ValueError):
        pass

    def parse_spec_file(path):
        raise ImportError("spec_frontmatter not available")

    def _is_nfr_family(frontmatter):
        spec_id = frontmatter.get("id") if isinstance(frontmatter, dict) else None
        spec_type = frontmatter.get("type") if isinstance(frontmatter, dict) else None
        return (isinstance(spec_id, str) and spec_id.startswith("NFR-")) or spec_type == "nfr"

    is_nfr_family = _is_nfr_family

    def nfr_match_reasons(spec, nfr):
        return []

    def nfr_is_bound_or_waived(spec, nfr):
        return True

    PROMOTION_GAP_KINDS = frozenset({
        "awaiting_upstream_spec", "awaiting_authorization",
        "awaiting_external_precondition", "incomplete_content", "awaiting_decision",
    })

    def promotion_gap_summary(frontmatters):
        return {"denominator": 0, "by_kind": {}}

    def status_error_for_spec(frontmatter, status):
        if _is_nfr_family(frontmatter) and status not in NFR_FAMILY_STATUSES:
            return (
                "NFR-family specs (id starts with NFR- or type is nfr) must use "
                f"status active or retired; got {status}"
            )
        if status not in VALID_SPEC_STATUSES:
            valid_sorted = sorted(VALID_SPEC_STATUSES)
            return f"invalid status {status!r} — valid values: {', '.join(valid_sorted)}"
        return None

    def _check_column_override(override):
        """Fallback when spec_frontmatter is unavailable."""
        problems = []
        if not isinstance(override, dict):
            problems.append("board_column_defaults must be a mapping")
            return problems
        raw_states = override.get("default_state")
        if raw_states is not None:
            if not isinstance(raw_states, dict):
                problems.append("board_column_defaults.default_state must be a mapping")
            else:
                for col_id, state in raw_states.items():
                    if col_id not in VALID_SPEC_STATUSES:
                        problems.append(
                            f"board_column_defaults.default_state has unknown status {col_id!r}"
                        )
                    elif state not in _VALID_COLUMN_STATES_FB:
                        problems.append(
                            f"board_column_defaults.default_state[{col_id!r}] has invalid"
                            f" value {state!r} — must be one of: expanded, collapsed, hidden"
                        )
        raw_order = override.get("order")
        if raw_order is not None:
            if not isinstance(raw_order, list):
                problems.append("board_column_defaults.order must be a list")
            elif set(raw_order) != set(VALID_SPEC_STATUSES) or len(raw_order) != len(VALID_SPEC_STATUSES):
                missing = sorted(set(VALID_SPEC_STATUSES) - set(raw_order))
                extra = sorted(set(raw_order) - set(VALID_SPEC_STATUSES))
                problems.append(
                    f"board_column_defaults.order must be a full permutation"
                    f" (missing={missing}, extra={extra})"
                )
        return problems


_NFRS_REQUIRED_TYPES = frozenset({"feature", "bugfix", "refactor"})
_HISTORICAL_CHECKBOX_DISPOSITIONS = "historical-checkbox-status-dispositions.json"
_ALLOWED_HISTORICAL_CHECKBOX_DISPOSITIONS = frozenset({
    "intentional_historical_record",
    "unresolved_evidence_gap",
})


_SCOPE_ANCHOR_RE = re.compile(r"\{\{[^}]*\}\}")


def _validate_scope_glob_list(key: str, value: object) -> list[str]:
    """Shared glob-list checks for scope.write/deny/read (SPEC-300-001 R6)."""
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"scope.{key} must be a list of strings"]
    errors: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"scope.{key}[{index}] must be a string")
            continue
        if item.startswith("/") or item.startswith("~"):
            errors.append(f"scope.{key}[{index}] must not be an absolute path: {item!r}")
        if ".." in Path(item).parts:
            errors.append(f"scope.{key}[{index}] must not contain '..': {item!r}")
        if _SCOPE_ANCHOR_RE.search(item):
            errors.append(f"scope.{key}[{index}] must not use a {{{{...}}}} anchor: {item!r}")
    return errors


def validate_resolved_blocker_fields(fm: dict) -> list[str]:
    """SPEC-355 R2: a spec outside ``status: blocked`` should never carry a
    live top-level blocker field.

    ``unblock_spec.py::finalize()`` relocates these six fields into
    ``unblock_history[-1].resolved_blocker`` on a successful ``blocked ->
    ready`` transition (SPEC-355 R1); this is the mechanical, non-model
    backstop that catches any other path (a hand-edit, a different tool, a
    prior version of this kit before SPEC-355) that left them live instead.

    ``WARNING``, not a hard error (SPEC-244 lesson: a check compared against
    historical state, not the policy in force when it was written, can never
    be satisfied — 37 already-``done`` specs in this repository alone predate
    this fix and would otherwise fail pre-commit the moment anyone touches
    them for an unrelated reason). Every *new* ``blocked -> ready`` transition
    is clean by construction as of SPEC-355; this warning exists to surface
    the pre-existing backlog for a future mechanical repair (``doctor.py
    --fix``), not to block unrelated work on old specs.
    """
    if fm.get("status") == "blocked":
        return []
    from unblock_spec import RESOLVED_BLOCKER_FIELDS

    present = [key for key in RESOLVED_BLOCKER_FIELDS if key in fm]
    if not present:
        return []
    return [
        "WARNING: resolved blocker field(s) still present at status "
        f"{fm.get('status')!r}: {', '.join(present)} "
        "(unblock_spec.py::finalize() should have relocated these into "
        "unblock_history[-1].resolved_blocker on the blocked -> ready "
        "transition — SPEC-355)"
    ]


def validate_scope(fm: dict) -> list[str]:
    """Validate the optional ``scope:`` block (SPEC-300-001 R6).

    ``scope:`` is entirely optional — absent means the project-root default
    (SPEC-300 § Defaults). When present, ``write``/``deny`` must be lists of
    project-root-relative strings with no absolute paths, no ``..``
    components, and no ``{{...}}`` anchors (scope must never reach outside
    the project via a path_vars anchor). ``read`` is either the literal
    string ``unrestricted`` or the same kind of list.
    """
    scope = fm.get("scope")
    if scope is None:
        return []
    if not isinstance(scope, dict):
        return ["scope must be a mapping"]
    errors: list[str] = []
    allowed_keys = {"write", "deny", "read"}
    unknown = sorted(set(scope) - allowed_keys)
    if unknown:
        errors.append("scope has unknown fields: " + ", ".join(unknown))
    errors.extend(_validate_scope_glob_list("write", scope.get("write")))
    errors.extend(_validate_scope_glob_list("deny", scope.get("deny")))
    read = scope.get("read", "unrestricted")
    if read != "unrestricted":
        errors.extend(_validate_scope_glob_list("read", read))
        if not isinstance(read, list):
            errors.append("scope.read must be 'unrestricted' or a list of strings")
    return errors


_SCOPE_AMENDMENTS_HEADING = re.compile(r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", re.MULTILINE)
_SCOPE_AMENDMENTS_SEPARATOR = re.compile(r"^\|[\s:|-]*\|?$")


def validate_scope_amendments(content: str) -> list[str]:
    """Validate ``## Scope Amendments`` rows (SPEC-300-001 R7).

    Columns: ``Date | Path or glob | Change (old -> new) | Reason |
    Approved by``. Every non-empty row's ``Approved by`` cell must be
    exactly ``human`` or ``human:<name>``; the table may be empty.
    """
    match = _SCOPE_AMENDMENTS_HEADING.search(content)
    if not match:
        return []
    errors: list[str] = []
    for line in match.group(1).split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if _SCOPE_AMENDMENTS_SEPARATOR.match(stripped):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not any(cells):
            continue
        if cells[0] == "Date":  # header row
            continue
        if len(cells) < 5:
            continue  # malformed row shape is not this validator's concern
        approved_by = cells[4]
        if not approved_by:
            continue
        if approved_by != "human" and not re.fullmatch(r"human:.+", approved_by):
            errors.append(
                f"## Scope Amendments row 'Approved by' must be 'human' or 'human:<name>', got {approved_by!r}"
            )
    return errors


def validate_ac_amendments(content: str, spec_file: Path) -> list[str]:
    """Detect changed AC text against the last ready revision, when available."""
    try:
        root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=spec_file.parent.parent, text=True, capture_output=True, check=True).stdout.strip())
        relative = spec_file.resolve().relative_to(root)
        prior = subprocess.run(["git", "log", "-G", r"^status: ready$", "--format=%H", "--", str(relative)], cwd=root, text=True, capture_output=True, check=True).stdout.splitlines()
        if not prior:
            return []
        old = subprocess.run(["git", "show", f"{prior[0]}:{relative}"], cwd=root, text=True, capture_output=True)
        if old.returncode:
            return []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    def acs(text: str) -> dict[str, str]:
        block = re.search(r"^## Acceptance Criteria\s*$([\s\S]*?)(?=^## |\Z)", text, re.MULTILINE)
        items = re.findall(r"^- \[[ x]\]\s*(AC\d+[^\n]*)", block.group(1), re.MULTILINE) if block else []
        return {re.match(r"AC\d+", item).group(0): item for item in items}
    current, previous = acs(content), acs(old.stdout)
    deleted = sorted(set(previous) - set(current))
    changed = [key for key in sorted(set(previous) & set(current)) if previous[key] != current[key]]
    amendment = re.search(r"^## AC Amendments\s*$([\s\S]*?)(?=^## |\Z)", content, re.MULTILINE)
    table = amendment.group(1) if amendment else ""
    findings = [f"ac_amendment_deleted: {previous[key]}" for key in deleted]
    for key in changed:
        old_text, new_text = previous[key], current[key]
        if old_text not in table or new_text not in table:
            findings.append(f"ac_amendment_undocumented: {new_text}")
    return findings


def _historical_checkbox_disposition(
    spec_file: Path, findings: list[dict]
) -> str | None:
    """Return a disposition only when project-owned evidence matches exactly.

    The optional inventory records unresolved historical checkbox text rather
    than changing it. Any absent, malformed, stale, partial, or reordered data
    is non-authoritative and leaves the ordinary terminal-state errors intact.
    """
    inventory = spec_file.parent.parent / _HISTORICAL_CHECKBOX_DISPOSITIONS
    try:
        payload = json.loads(inventory.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(spec_file.name)
    if not isinstance(entry, dict):
        return None
    disposition = entry.get("disposition")
    if disposition not in _ALLOWED_HISTORICAL_CHECKBOX_DISPOSITIONS:
        return None
    expected = entry.get("findings")
    if not isinstance(expected, list) or expected != findings:
        return None
    return str(disposition)


# SPEC-163: material decision briefs live in the existing QUESTIONS spec.  This
# validator deliberately checks only the mechanical contract; evidence quality
# and recommendation logic are reviewed by an independent role in the skill.
_DECISION_BRIEF_REQUIRED_FIELDS = (
    "Question",
    "Measured facts",
    "Reproduction",
    "Evidence",
    "Options",
    "Consequences",
    "Recommendation",
    "Assumptions",
    "Neighbouring questions",
    "Evidence timestamp",
    "Proposed authority",
)
_DECISION_BRIEF_HEADING = re.compile(r"^##\s+Decision Brief\s*$", re.MULTILINE)
_BRIEF_FIELD = re.compile(r"^\*\*(.+?):\*\*\s*(.+)$", re.MULTILINE)
_EVIDENCE_REFERENCE = re.compile(r"\[[^\]]+\]\(([^)]+)\)|`([^`]+)`")


def validate_decision_briefs(content: str, project_root: Path) -> list[str]:
    """Return mechanical findings for every `## Decision Brief` block.

    The block terminates at the next level-two heading.  A missing block is
    valid: ordinary questions retain the lightweight address-issues flow.
    """
    findings: list[str] = []
    starts = list(_DECISION_BRIEF_HEADING.finditer(content))
    for number, start in enumerate(starts, start=1):
        next_heading = re.search(r"^##\s+", content[start.end():], re.MULTILINE)
        end = start.end() + next_heading.start() if next_heading else len(content)
        block = content[start.end():end]
        fields = {match.group(1).strip(): match.group(2).strip() for match in _BRIEF_FIELD.finditer(block)}
        prefix = f"decision brief {number}"
        for field in _DECISION_BRIEF_REQUIRED_FIELDS:
            if not fields.get(field):
                findings.append(f"{prefix}: missing required field: {field}")

        reproduction = fields.get("Reproduction", "")
        if reproduction and not re.search(r"`[^`]+`|\b(?:python3?|pytest|rg|git|find|ls)\b", reproduction):
            findings.append(f"{prefix}: Reproduction must include a reproducible command or query")

        timestamp = fields.get("Evidence timestamp", "")
        if timestamp:
            try:
                from datetime import datetime
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                findings.append(f"{prefix}: Evidence timestamp must be ISO-8601")

        evidence = fields.get("Evidence", "")
        if evidence:
            references = [a or b for a, b in _EVIDENCE_REFERENCE.findall(evidence)]
            if not references:
                findings.append(f"{prefix}: Evidence must include a resolvable artifact reference")
            for reference in references:
                candidate = project_root / reference
                if reference.startswith(("http://", "https://")):
                    continue
                if not candidate.is_file():
                    findings.append(f"{prefix}: unresolvable evidence reference: {reference}")
    return findings


# SPEC-299 R2/R3: a `## Report Action Log` table records, per scanned report,
# what happened to its own `## Open Questions` / `## Blocked Specs` content.
# Mirrors the decision-brief validator's shape (mechanical contract only): a
# closed-vocabulary Action column, checked against a fixed prefix set rather
# than free text. Heading match is deliberately exact-case (`Report Action
# Log`, capitalized) -- that is the canonical form this spec introduces.
# `SPEC-QUESTIONS-005.md`'s pre-existing `## Report action log` (lowercase
# "action log") predates this spec, is its named reference for the *table
# shape* only (not the validated heading spelling), and is explicitly out of
# scope for rewriting (see SPEC-299's Out of Scope). A case-insensitive match
# would retroactively fail every free-prose "Action taken" cell in that file;
# `test_spec_299_report_questions_flow.py::test_spec_questions_005_is_exempt_from_the_new_closed_vocabulary`
# pins this boundary so it cannot regress silently.
_REPORT_ACTION_LOG_HEADING = re.compile(r"^##\s+Report Action Log\s*$", re.MULTILINE)
_REPORT_ACTION_LOG_ALLOWED_PREFIXES = (
    "none_found",
    "consolidated_into ",
    "resolved_in_report",
    "deferred: ",
)
_TABLE_SEPARATOR_ROW = re.compile(r"^\|[\s:|-]+\|$")

# SPEC-317: gates `validate_report_headings` by report filename date so it
# never retroactively flags a report predating the coordinator-authored-
# report contract (LOOP.md Step 14a). Set to SPEC-317's own `created` date;
# a report dated on or before this is silently exempt, which covers every
# report SPEC-QUESTIONS-006 swept (2026-09-04 through 2026-09-07 inclusive),
# including its two 2026-09-07 entries.
_REPORT_HEADINGS_MIN_DATE = "2026-09-07"
_REPORT_FILENAME_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})-nightshift-report")
_REQUIRED_REPORT_HEADINGS = ("## Blocked Specs", "## Open Questions")


def validate_report_headings(report_path: Path, min_date: str = _REPORT_HEADINGS_MIN_DATE) -> list[str]:
    """Flag a coordinator-authored report (SPEC-317) missing the
    `## Blocked Specs` / `## Open Questions` headings LOOP.md Step 14 (and
    Step 14a, for coordinator-authored reports) require.

    Gated by the report's filename date, not by who wrote it — mechanical
    enforcement has no way to tell a dispatched-worker report from a
    coordinator-authored one, and doesn't need to: both paths owe the same
    three sections as of `min_date`. A report dated on or before `min_date`
    (SPEC-317's own `created` date) predates this mechanical check and is
    never flagged, so it cannot retroactively fail any of
    `SPEC-QUESTIONS-006`'s 10 historical gap reports (or the 3 that already
    carry the headings).
    """
    match = _REPORT_FILENAME_DATE.match(report_path.name)
    if not match or match.group(1) <= min_date:
        return []
    content = report_path.read_text(encoding="utf-8")
    findings = []
    for heading in _REQUIRED_REPORT_HEADINGS:
        if not re.search(rf"^{re.escape(heading)}\s*$", content, re.MULTILINE):
            findings.append(f"missing required heading: {heading!r}")
    return findings


def validate_report_action_log(content: str) -> list[str]:
    """Return mechanical findings for every `## Report Action Log` table
    (SPEC-299). Enumerates every occurrence of the heading, mirroring
    ``validate_decision_briefs``'s multi-block handling.

    Each table's last column is the Action; every data row's Action must be
    exactly ``none_found``/``resolved_in_report`` or start with
    ``consolidated_into ``/``deferred: ``. A missing section is valid — not
    every report or spec carries one.
    """
    findings: list[str] = []
    starts = list(_REPORT_ACTION_LOG_HEADING.finditer(content))
    for block_number, start in enumerate(starts, start=1):
        next_heading = re.search(r"^##\s+", content[start.end():], re.MULTILINE)
        end = start.end() + next_heading.start() if next_heading else len(content)
        block = content[start.end():end]
        table_rows = [
            line.strip() for line in block.splitlines()
            if line.strip().startswith("|") and line.strip().endswith("|")
        ]
        # A well-formed table is header, then a `|---|---|` separator, then
        # data rows. Drop the separator row(s) first, then the header (the
        # first remaining row) — this only discards a real data row if the
        # table omits its header, which is not a shape this spec's format
        # produces.
        non_separator_rows = [row for row in table_rows if not _TABLE_SEPARATOR_ROW.fullmatch(row)]
        data_rows = non_separator_rows[1:] if non_separator_rows else []
        prefix = f"report action log {block_number}" if len(starts) > 1 else "report action log"
        for row_number, row in enumerate(data_rows, start=1):
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            action = cells[-1] if cells else ""
            if not action.startswith(_REPORT_ACTION_LOG_ALLOWED_PREFIXES):
                findings.append(
                    f"{prefix} row {row_number}: unrecognized action value: {action!r}"
                )
    return findings


def validate_reuse_gate(content: str) -> list[str]:
    """Reject unsubstantiated parallel command/store plans (SPEC-163 R12)."""
    plan_match = re.search(r"^##\s+Implementation Plan\s*$([\s\S]*?)(?=^##\s+|\Z)", content, re.MULTILINE)
    if not plan_match:
        return []
    lowered = plan_match.group(1).lower()
    introduces_parallel = bool(
        re.search(r"(?:new|separate|parallel)\s+(?:\w+\s+){0,2}(?:command|ledger|store)", lowered)
    )
    if not introduces_parallel:
        return []
    required = ("measurable gap", "reuse", "acceptance criteria")
    missing = [item for item in required if item not in lowered]
    if missing:
        return [
            "reuse gate: parallel command/store requires measurable gap evidence, "
            "a smaller reuse-based alternative, and an acceptance criterion; missing "
            + ", ".join(missing)
        ]
    return []


# ──────────────────────────────────────────────────────────────────────
# SPEC-071: portable path-variable validation (R9)
# ──────────────────────────────────────────────────────────────────────

# Shared code-span masking + known anchor names. path_vars is a canonical
# protocol file synced alongside this validator; fall back gracefully if a
# project .nightshift/ copy lacks it (then code-span masking is conservative).
try:
    import path_vars as _path_vars
    _ANCHOR_NAMES = set(_path_vars.ANCHOR_NAMES)
    _code_spans = _path_vars.code_spans
except ImportError:  # pragma: no cover - project-copy fallback
    _path_vars = None
    _ANCHOR_NAMES = {"PROJECT_ROOT", "ARGO_HOME", "HOME"}

    def _code_spans(text):  # minimal fence/inline-span detector
        spans = []
        for m in re.finditer(r"```.*?```|~~~.*?~~~", text, re.DOTALL):
            spans.append((m.start(), m.end()))
        for m in re.finditer(r"`[^`\n]+`", text):
            if not any(s <= m.start() < e for s, e in spans):
                spans.append((m.start(), m.end()))
        return spans

# Known lowercase prompt vars (prompt_engine namespace) that may legitimately
# appear as {{lower}} tokens in spec prose without being "unknown".
_KNOWN_PROMPT_VARS = frozenset({
    "spec_content", "spec_id", "spec_title", "project_root", "argo_home",
    "model", "agent", "phase", "version", "created",
})

# Home-style absolute roots that leak host/VM layout (R9c). Anchor-scoped, NOT a
# raw /segment regex — fires only on these known-leak prefixes so the detector
# catches /home/ and VM /sessions/ leaks the old /Users/-only grep missed
# WITHOUT flagging /api/v1/... route docs.
_LEAK_ROOTS = ("/Users/", "/home/", "/sessions/", "/var/folders/", "/private/var/folders/")

# kit_version at/after which prose absolute-path leaks flip from WARN -> ERROR.
# Until every project has synced the migrated kit, prose leaks are a transition
# WARNING (auto-fixable by the one-shot migration); the registry ERROR (R9a) is
# immediate because regen auto-fixes it.
PROSE_ERROR_KIT_VERSION = "2.24.0"


def _read_kit_version(config_path: Path) -> str | None:
    """Read kit_version from a config.yaml file.  Returns None on any failure.

    Canonical config files are YAML streams, with top-level sections separated
    by ``---``.  Merge mapping documents so a version in a later section is
    read just like a single-document project config.  All exceptions are
    silently caught so a missing or malformed config always produces the safe
    default (R3).
    """
    if config_path is None or not config_path.is_file():
        return None
    try:
        raw = config_path.read_text(encoding="utf-8")
        cfg = {}
        for document in yaml.safe_load_all(raw):
            if isinstance(document, dict):
                cfg.update(document)
        val = cfg.get("kit_version")
        return str(val) if val is not None else None
    except Exception:
        return None


def _kit_version_gte(version_str: str | None, threshold: str) -> bool:
    """Return True if version_str >= threshold (both dotted-int semver strings).

    Returns False on any parse failure so the caller degrades to the safe
    default (WARNING).  The comparison is inclusive: ``2.24.0 >= 2.24.0``
    is True (AC2 boundary).
    """
    if version_str is None:
        return False
    try:
        def _to_tuple(s: str):
            return tuple(int(x) for x in s.strip().split("."))
        return _to_tuple(version_str) >= _to_tuple(threshold)
    except Exception:
        return False


def _in_any_span(idx: int, spans: list) -> bool:
    return any(s <= idx < e for s, e in spans)


def _detect_leak_paths(text: str) -> list[str]:
    """R9c: anchor-scoped residual-absolute-path detector.

    Return the leaked path-like strings that start with a known home-style root
    and are NOT inside a code fence/span. Does not flag /api/v1/... route docs
    (those don't start with a _LEAK_ROOTS prefix).
    """
    spans = _code_spans(text)
    found = []
    # Match a leak root followed by path chars (stop at whitespace/quote/paren).
    pat = re.compile(
        r"(?:" + "|".join(re.escape(r) for r in _LEAK_ROOTS) + r")[^\s\"'`)\]]*"
    )
    for m in pat.finditer(text):
        if _in_any_span(m.start(), spans):
            continue
        found.append(m.group(0))
    return found


def _detect_unknown_tokens(text: str) -> list[str]:
    """R9e: {{...}} tokens that are neither a known UPPER path-var, a known
    lowercase prompt var, nor inside a code span. Returns the offending tokens."""
    spans = _code_spans(text)
    bad = []
    for m in re.finditer(r"\{\{\s*([^{}]*?)\s*\}\}", text):
        if _in_any_span(m.start(), spans):
            continue
        name = m.group(1)
        if name in _ANCHOR_NAMES:
            continue
        if name in _KNOWN_PROMPT_VARS:
            continue
        # Also accept a well-formed lower_snake token (prompt namespace) so we
        # don't flag every prompt var; flag only clearly-malformed/unknown ones.
        if re.fullmatch(r"[a-z][a-z0-9_]*", name):
            continue
        bad.append(m.group(0))
    return bad


def _detect_unquoted_yaml_token(fm_text: str) -> list[str]:
    """R9d: reject unquoted {{ }} values in YAML frontmatter (they break YAML
    flow-mapping parsing or are silently misread). Returns offending lines."""
    bad = []
    for line in fm_text.split("\n"):
        # key: {{TOKEN}}...   without surrounding quotes
        m = re.match(r"\s*[\w.-]+:\s*(.+)$", line)
        if not m:
            continue
        value = m.group(1).strip()
        if value.startswith("{{") and not (
            value.startswith('"') or value.startswith("'")
        ):
            bad.append(line.strip())
    return bad


def _detect_traversal(text: str) -> list[str]:
    """R9f: forbid `..` traversal in {{PROJECT_ROOT}}-anchored path tokens.
    Cross-project refs must route by spec name, never `../` arithmetic."""
    spans = _code_spans(text)
    bad = []
    for m in re.finditer(r"\{\{PROJECT_ROOT\}\}/([^\s\"'`)\]]*)", text):
        if _in_any_span(m.start(), spans):
            continue
        rel = m.group(1)
        parts = rel.split("/")
        if ".." in parts:
            bad.append(m.group(0))
    return bad


def _load_directory_frontmatters(specs_dir: Path) -> list[dict]:
    """Load valid frontmatters for cross-spec static checks."""
    loaded = []
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8").split("\n---", 1)[0][3:]) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(parsed, dict) and parsed.get("id"):
            loaded.append(parsed)
    return loaded


# SPEC-270 R1: findings whose message already carries a named
# ``release_handoff`` constant are keyed on that constant's exact string —
# checked first so they never fall through to the shorter ad-hoc markers
# below.  These constants appear as a substring of the rendered message
# (e.g. ``f"{relative}: {ORPHANED_HANDOFF_ARTIFACT_ERROR}"``), never the whole
# message, so matching is substring containment, not equality.
_NAMED_FINDING_FAMILIES: tuple[str, ...] = (
    "state_rationale_required_missing", "state_rationale_malformed",
    "state_rationale_reason_invalid", "state_rationale_reconsider_required",
    "state_rationale_schema", "state_rationale_placeholder_reason",
    "state_rationale_placeholder_reconsider_when", "state_rationale_status_mismatch",
    "state_rationale_unverified_external", "state_rationale_evidence_path_escape",
    "state_rationale_broken_evidence_link", "state_rationale_broken_evidence_anchor",
    "state_rationale_index_malformed", "state_rationale_record_not_indexed",
    "state_rationale_record_wrong_type", "state_rationale_record_wrong_owner",
    "state_rationale_record_path_escape", "state_rationale_record_unreadable",
    "state_rationale_stale_snapshot", "state_rationale_transition_target_mismatch",
    "state_rationale_legacy_missing", "state_rationale_record_required",
    "state_rationale_record_pending", "state_rationale_adoption_regressed",
    "state_rationale_adoption_required", "state_rationale_validation_unavailable",
    release_handoff.MISSING_RELEASE_HANDOFF_DECLARATION_ERROR,
    release_handoff.STRANDED_PENDING_HANDOFF_ERROR,
    release_handoff.ORPHANED_HANDOFF_ARTIFACT_ERROR,
    release_handoff.AMBIGUOUS_HANDOFF_ARTIFACT_ERROR,
    release_handoff.UNTRACKED_HANDOFF_ARTIFACT_ERROR,
    release_handoff.MISSING_STRANDED_DISPOSITION_ERROR,
    release_handoff.INVALID_STRANDED_DISPOSITION_ERROR,
)

# SPEC-270 R1: ad-hoc findings have no named constant in code. Each entry
# pairs a stable, short family key with the fixed marker phrase that
# identifies it in the rendered message — the "fixed, non-parameterized
# portion" the spec requires. Never the raw message: most of these messages
# interpolate a spec ID, file path, line number, or arbitrary prose (e.g. the
# text of an unchecked checkbox), and keying on the raw message would explode
# one conceptual finding into many singleton "families". Ordered; first match
# wins, evaluated only after the named constants above.
_AD_HOC_FINDING_FAMILIES: tuple[tuple[str, str], ...] = (
    ("done-spec-unchecked-checkbox", "but has an unchecked checkbox in"),
    ("missing-required-field-id", "missing required field: id"),
    ("missing-required-field-status", "missing required field: status"),
    ("missing-required-field-nfrs", "missing required field: nfrs"),
    ("invalid-status-value", "valid values:"),
    ("legacy-planning-status", "legacy status 'planning'"),
    # attachments — two distinct fixed shapes; "attachments[" (not bare
    # "attachments") avoids swallowing unrelated messages that merely mention
    # the word in passing.
    ("attachments-list-shape", "attachments must be a list of mappings"),
    ("attachments-item-shape", "attachments["),
    ("followup-shape", "followup."),
    # promotion_gap — kept as four distinct families (not one broad
    # "promotion_gap" marker) because each is a materially different failure:
    # wrong shape, invalid kind, missing reason, missing upstream_spec. The
    # more specific real_use_evidence marker below is checked first so it
    # cannot be shadowed by the shorter "requires a non-empty reason" marker.
    ("promotion-gap-not-mapping", "promotion_gap must be a mapping with kind and reason"),
    ("promotion-gap-kind-invalid", "promotion_gap kind must be one of:"),
    ("promotion-gap-upstream-required", "promotion_gap awaiting_upstream_spec requires upstream_spec"),
    ("real-use-evidence-reason-required", "real_use_evidence.not_applicable requires a non-empty reason"),
    ("promotion-gap-reason-required", "requires a non-empty reason"),
    ("nfr-waivers-shape", "nfr_waivers"),
    ("nfr-reconciliation-required", "NFR reconciliation required"),
    ("scope-tags-shape", "scope_tags"),
    ("transfer-refusal-shape", "transfer_refusal must be a non-empty string"),
    ("unquoted-template-token", "unquoted {{ }} token in frontmatter value"),
    ("unknown-template-token", "unknown template token"),
    ("path-traversal-token", "traverses past PROJECT_ROOT"),
    ("absolute-path-leak", "absolute path leak"),
    ("missing-body-h1", "missing body H1 title"),
    ("block-reason-as-title", "first body H1 is 'Block Reason'"),
    ("missing-frontmatter-open-delimiter", "missing opening frontmatter delimiter"),
    ("missing-frontmatter-close-delimiter", "missing closing frontmatter delimiter"),
    ("release-handoff-artifact-required", "release-impact spec requires a release handoff artifact"),
    ("release-handoff-awaiting-repin", "release handoff awaits coordinator re-pin"),
    # SPEC-332: delivered-but-not-closed and board/file status divergence.
    ("release-handoff-completed-spec-not-done", "release handoff completed"),
    ("status-sync-mismatch", "status-sync mismatch"),
    ("ac-amendment-undocumented", "ac_amendment_undocumented:"),
)

# A finding matching neither table above still needs a stable, machine-
# comparable key rather than silently disappearing from the summary or being
# merged into an unrelated bucket.
_UNCLASSIFIED_FINDING_FAMILY = "unclassified-finding"

# SPEC-270: only a non-terminal spec can currently own a finding family — a
# finished or retired spec's historical claim does not keep future findings
# owned once the spec itself is closed.
_TERMINAL_SPEC_STATUSES = frozenset({"done", "superseded", "retired"})


def classify_finding_family(message: str) -> str:
    """Return the stable finding-family key for a rendered validator message.

    Severity is not family identity: a ``WARNING: `` prefix is stripped
    before classification. See the two pattern tables above for the
    derivation rule (SPEC-270 R1).
    """
    msg = message[len("WARNING: "):] if message.startswith("WARNING: ") else message
    for constant in _NAMED_FINDING_FAMILIES:
        if constant in msg:
            return constant
    for family_key, marker in _AD_HOC_FINDING_FAMILIES:
        if marker in msg:
            return family_key
    return _UNCLASSIFIED_FINDING_FAMILY


def _open_spec_family_owners(frontmatters: list[dict]) -> dict[str, list[str]]:
    """Map finding-family key -> sorted open spec IDs claiming ownership.

    Matching is exact string equality between a finding's derived family key
    and a spec's ``owns_findings`` entries — never fuzzy or substring (SPEC-270
    matching rule). Multiple open specs may declare the same family; both are
    recorded (R2's "owning spec IDs", plural — a collision is not a conflict).
    """
    owners: dict[str, set[str]] = {}
    for fm in frontmatters:
        if not isinstance(fm, dict):
            continue
        status = str(fm.get("status", "")).lower()
        if status in _TERMINAL_SPEC_STATUSES:
            continue
        spec_id = fm.get("id")
        if not isinstance(spec_id, str) or not spec_id.strip():
            continue
        owns = fm.get("owns_findings")
        if not isinstance(owns, list):
            continue
        for family in owns:
            if isinstance(family, str) and family.strip():
                owners.setdefault(family, set()).add(spec_id)
    return {family: sorted(ids) for family, ids in owners.items()}


def finding_family_summary(results: dict, frontmatters: list[dict]) -> dict:
    """SPEC-270 R2/R4: per-family finding counts with owning open spec IDs.

    ``results`` is the ``{filename: [message, ...]}`` shape ``validate_directory``
    / ``validate_file`` already produce. Output is sorted by family key with
    sorted owner lists so two runs are byte-diffable (AC2), and each family
    carries an explicit ``unowned`` flag — growth in the unowned set is the
    signal a reviewer needs; growth in the owned set is not (R4).
    """
    owners_by_family = _open_spec_family_owners(frontmatters)
    counts: dict[str, int] = {}
    for errors in results.values():
        for msg in errors:
            key = classify_finding_family(msg)
            counts[key] = counts.get(key, 0) + 1

    families = []
    for family in sorted(counts):
        owners = owners_by_family.get(family, [])
        families.append({
            "family": family,
            "count": counts[family],
            "owners": owners,
            "unowned": len(owners) == 0,
        })

    total = sum(counts.values())
    unowned_total = sum(f["count"] for f in families if f["unowned"])
    return {
        "total_findings": total,
        "unowned_findings": unowned_total,
        "owned_findings": total - unowned_total,
        "families": families,
    }


def diff_finding_family_summaries(baseline: dict, current: dict) -> dict:
    """SPEC-270 R3: compare two ``finding_family_summary`` outputs.

    A family whose count is unchanged but whose owners changed, or an overall
    total that stays flat while one family shrinks and a different family
    grows by the same amount, is still reported as a change — never collapsed
    into "no-op" by comparing only the grand total.
    """
    before = {f["family"]: f for f in baseline.get("families", [])}
    after = {f["family"]: f for f in current.get("families", [])}
    changes = []
    for family in sorted(set(before) | set(after)):
        b = before.get(family)
        a = after.get(family)
        if b is None:
            changes.append({
                "family": family, "change": "added",
                "count": a["count"], "owners": a["owners"],
            })
        elif a is None:
            changes.append({
                "family": family, "change": "removed",
                "count": b["count"], "owners": b["owners"],
            })
        elif b["count"] != a["count"] or b["owners"] != a["owners"]:
            changes.append({
                "family": family,
                "change": "changed",
                "before": {"count": b["count"], "owners": b["owners"]},
                "after": {"count": a["count"], "owners": a["owners"]},
            })
    return {
        "changed": bool(changes),
        "changes": changes,
        "total_before": baseline.get("total_findings", 0),
        "total_after": current.get("total_findings", 0),
    }


def declaring_handoff_spec_ids(frontmatters: list[dict]) -> list[str]:
    """Return the spec IDs whose declaration resolves a handoff artifact.

    Only ``impact: required`` reaches ``validate_artifact``; an ``exempt``
    declaration names no artifact, so an artifact sitting beside an exempt spec
    is still validated by nothing.  IDs repeat when two spec files share one
    ``id`` — fleet uniqueness is warning-only — and the sweep needs that count.
    """
    ids = []
    for frontmatter in frontmatters:
        declaration = frontmatter.get("release_handoff")
        if isinstance(declaration, dict) and declaration.get("impact") == "required":
            ids.append(str(frontmatter.get("id", "")))
    return ids


def _git(canonical: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", str(canonical), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def handoff_tracked_paths(canonical: Path) -> set[str] | None:
    """Return canonical-relative tracked artifact paths, or None if unjudgeable.

    Returning ``None`` is deliberate rather than an empty set: outside a
    repository, or under a path git is told to ignore — which is every private
    install, whose kit directory is never committed — "untracked" is the
    designed state and reporting it against every artifact would be noise.
    """
    if not (canonical / release_handoff.HANDOFF_DIR).is_dir():
        return None
    inside = _git(canonical, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    ignored = _git(canonical, "check-ignore", "-q", release_handoff.HANDOFF_DIR)
    if ignored is None or ignored.returncode == 0:
        return None
    listed = _git(canonical, "ls-files", "-z", "--", release_handoff.HANDOFF_DIR)
    if listed is None or listed.returncode != 0:
        return None
    return {path for path in listed.stdout.split("\0") if path}


def _tracked_paths_for(canonical: Path, dirname: str) -> set[str] | None:
    """Return canonical-relative tracked paths under ``dirname``, or None.

    Shared generic form of ``handoff_tracked_paths`` (SPEC-252) used by the
    SPEC-272 reports/runs sweeps. ``None`` is deliberate rather than an empty
    set — see ``handoff_tracked_paths``'s docstring for why.
    """
    if not (canonical / dirname).is_dir():
        return None
    inside = _git(canonical, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    ignored = _git(canonical, "check-ignore", "-q", dirname)
    if ignored is None or ignored.returncode == 0:
        return None
    listed = _git(canonical, "ls-files", "-z", "--", dirname)
    if listed is None or listed.returncode != 0:
        return None
    return {path for path in listed.stdout.split("\0") if path}


def reports_tracked_paths(canonical: Path) -> set[str] | None:
    return _tracked_paths_for(canonical, artifact_reachability.REPORTS_DIR)


def runs_tracked_paths(canonical: Path) -> set[str] | None:
    return _tracked_paths_for(canonical, artifact_reachability.RUNS_DIR)


def all_corpus_spec_ids(frontmatters: list[dict]) -> list[str]:
    """Return every spec ID in the corpus regardless of status (SPEC-272).

    Reports and runs reachability is judged against a spec that "exists in
    the corpus, in any status" -- a ``done`` spec still legitimately owns its
    historical reports and runs. Unlike ``declaring_handoff_spec_ids`` this
    does not filter by ``release_handoff`` declaration.
    """
    return [str(fm.get("id", "")) for fm in frontmatters if fm.get("id")]


# BUG-023: matches a clean `(evidence: <path>)` or `(evidence: `<path>`)`
# annotation -- the parens may contain ONLY the (optionally backtick-quoted)
# path token, nothing else, so the reference is unambiguous and
# machine-parseable (R1). A path with surrounding prose (e.g. an explanatory
# aside before the closing paren) deliberately does not match.
_EVIDENCE_REF_RE = re.compile(r"\(evidence:\s*`?([^\s`()]+)`?\s*\)")

# BUG-023: template_version at/above this threshold must back every checked LE
# item with an `(evidence: <path>)` reference that resolves to a real file.
# Chosen as one past the current template ceiling (v10, SPEC-300-001) so that
# no spec authored under an existing template version is retroactively broken
# -- see R4/AC3 and the corpus-wide count reported in the completion report.
EVIDENCE_REFERENCE_TEMPLATE_VERSION = 11


def _live_execution_items(body_lines: list[str]) -> tuple[set[str], set[str], dict[str, str | None]]:
    """Return checked/unchecked stable LE IDs and each checked ID's evidence ref.

    The evidence reference is the content of an inline ``(evidence: <path>)``
    annotation -- possibly wrapped onto a continuation line, since long LE
    entries commonly wrap (BUG-023). The format is inspired by the informal
    ``(evidence: `<path>`)`` idiom already seen in some of SPEC-300-003's LE
    items; it is a formal subset of that prose, not a full parse of it --
    the parens must contain only the (optionally backtick-quoted) path, no
    other prose, so an LE line with additional explanatory text inside the
    parens, or a differently worded reference (e.g. "See `<path>`."), is
    correctly treated as having no machine-parseable reference. Text
    describing the whole LE item, across all its wrapped lines, is joined
    before searching for the annotation, so it need not sit on the same
    physical line as the checkbox. ``None`` means no clean annotation was
    found anywhere in the item's text.
    """
    checked: set[str] = set()
    unchecked: set[str] = set()
    evidence: dict[str, str | None] = {}
    in_section = False
    current_id: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current_id, buffer
        if current_id is not None:
            text = " ".join(buffer)
            ref_match = _EVIDENCE_REF_RE.search(text)
            evidence[current_id] = ref_match.group(1) if ref_match else None
        current_id = None
        buffer = []

    for line in body_lines:
        if line.startswith("## "):
            flush()
            in_section = line.strip() == "## Live Execution Checklist"
            continue
        if not in_section:
            continue
        match = re.match(r"^\s*- \[([ xX])\]\s+\*\*(LE[1-9][0-9]*):\*\*(.*)$", line)
        if match:
            flush()
            le_id = match.group(2)
            if match.group(1).lower() == "x":
                checked.add(le_id)
                current_id = le_id
                buffer = [match.group(3)]
            else:
                unchecked.add(le_id)
        elif current_id is not None and line.strip() and line[:1].isspace():
            # Continuation line of the current (checked) LE item's own text.
            buffer.append(line.strip())
        else:
            flush()
    flush()
    return checked, unchecked, evidence


def _evidence_reference_exists(reference: str, spec_file: Path) -> bool:
    """Resolve an evidence reference relative to the spec file or kit dir."""
    if not reference or reference.startswith(("/", "~")) or ".." in Path(reference).parts or "://" in reference:
        return False
    roots = [spec_file.parent, spec_file.parent.parent]
    return any((root / reference).is_file() for root in roots)


def validate_real_use_evidence(
    fm: dict,
    body_lines: list[str],
    spec_file: Path,
    all_specs: list[dict] | None,
) -> list[str]:
    """Validate explicit live-proof completion or prospective delegation."""
    declaration = fm.get("real_use_evidence")
    if declaration is None:
        # Existing specs are intentionally grandfathered. Corpus migration is a
        # coverage metric, not a retroactive lifecycle failure.
        if fm.get("type") == "feature" and isinstance(fm.get("template_version"), int) and fm["template_version"] >= 8:
            message = "template v8 feature requires real_use_evidence policy"
            return [f"WARNING: {message}" if fm.get("status") == "draft" else message]
        return []
    errors: list[str] = []
    if not isinstance(declaration, dict):
        return ["real_use_evidence must be a mapping"]
    allowed = {"policy", "deferred", "reason"}
    unknown = sorted(set(declaration) - allowed)
    if unknown:
        errors.append("real_use_evidence has unknown fields: " + ", ".join(unknown))
    policy = declaration.get("policy")
    policies = {"required_before_done", "delegated_experiment", "not_applicable"}
    if policy not in policies:
        errors.append("real_use_evidence.policy must be required_before_done, delegated_experiment, or not_applicable")
        return errors
    checked, unchecked, evidence_refs = _live_execution_items(body_lines)
    status = str(fm.get("status", ""))
    deferred = declaration.get("deferred", [])
    if policy == "not_applicable":
        reason = declaration.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append("real_use_evidence.not_applicable requires a non-empty reason")
        if deferred:
            errors.append("real_use_evidence.not_applicable may not defer live items")
        touches = fm.get("touches")
        if not (
            isinstance(touches, list) and len(touches) == 1
            and isinstance(touches[0], str)
            and Path(touches[0]).suffix.lower() in {".css", ".md", ".txt"}
        ):
            errors.append("real_use_evidence.not_applicable is limited to one CSS/text file")
        return errors
    if declaration.get("reason") is not None:
        errors.append("real_use_evidence.reason is allowed only for not_applicable")
    if policy == "required_before_done":
        if deferred:
            errors.append("required_before_done may not contain deferred mappings")
        if status == "done" and unchecked:
            errors.append("status is 'done' but real_use_evidence requires completed live execution: " + ", ".join(sorted(unchecked)))
        # BUG-023: a checked LE item is proof of nothing on its own -- require an
        # evidence-artifact reference that actually exists on disk. Grandfathered
        # by template_version so no pre-existing spec is retroactively broken
        # (see EVIDENCE_REFERENCE_TEMPLATE_VERSION and the completion report's
        # corpus count for AC3/R4).
        template_version = fm.get("template_version")
        evidence_required = isinstance(template_version, int) and template_version >= EVIDENCE_REFERENCE_TEMPLATE_VERSION
        if status == "done" and evidence_required:
            for le_id in sorted(checked):
                reference = evidence_refs.get(le_id)
                if not reference or not _evidence_reference_exists(reference, spec_file):
                    errors.append(
                        f"real_use_evidence: checked live item {le_id} is missing a valid "
                        f"evidence reference (expected inline `(evidence: <path>)` pointing "
                        f"to an existing file); found: {reference!r}"
                    )
        return errors
    if not isinstance(deferred, list) or not deferred:
        return errors + ["delegated_experiment requires a non-empty deferred list"]
    mapped: list[str] = []
    corpus = all_specs if all_specs is not None else _load_directory_frontmatters(spec_file.parent)
    by_id = {str(candidate.get("id", "")): candidate for candidate in corpus}
    expected_fields = {
        "live_execution_id", "experiment_id", "descriptor", "hypothesis_ids",
        "instrumentation_spec_id", "lineage_record", "lineage_hash",
    }
    for index, raw in enumerate(deferred):
        prefix = f"real_use_evidence.deferred[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        if set(raw) != expected_fields:
            missing = sorted(expected_fields - set(raw))
            extra = sorted(set(raw) - expected_fields)
            errors.append(f"{prefix} must use the closed mapping; missing={missing}, extra={extra}")
            continue
        live_id = raw["live_execution_id"]
        if not isinstance(live_id, str) or not re.fullmatch(r"LE[1-9][0-9]*", live_id):
            errors.append(f"{prefix}.live_execution_id must match LE<number>; R/AC/NFR delegation is forbidden")
        else:
            mapped.append(live_id)
            if live_id in checked:
                errors.append(f"{prefix} maps checked live item {live_id}")
        reference = raw["lineage_record"]
        if not isinstance(reference, str) or not reference or reference.startswith(("/", "~")) or ".." in Path(reference).parts or "://" in reference:
            errors.append(f"{prefix}.lineage_record must be a safe relative SPEC-236 reference")
        lineage_hash = raw["lineage_hash"]
        if not isinstance(lineage_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", lineage_hash):
            errors.append(f"{prefix}.lineage_hash must be a lowercase SHA-256 digest")
        elif isinstance(reference, str):
            roots = [spec_file.parent, spec_file.parent.parent]
            lineage_path = next((root / reference for root in roots if (root / reference).is_file()), None)
            if lineage_path is not None:
                import hashlib
                if hashlib.sha256(lineage_path.read_bytes()).hexdigest() != lineage_hash:
                    errors.append(f"{prefix}.lineage_hash disagrees with immutable record")
        instrumentation_id = raw["instrumentation_spec_id"]
        if instrumentation_id == fm.get("id"):
            errors.append(f"{prefix}.instrumentation_spec_id may not self-reference")
        instrumentation = by_id.get(str(instrumentation_id))
        if instrumentation is None:
            errors.append(f"{prefix}.instrumentation_spec_id does not resolve")
        elif status == "done" and instrumentation.get("status") != "done":
            errors.append(f"{prefix}.instrumentation_spec_id must be done before source closure")
        if isinstance(instrumentation, dict) and fm.get("id") in (instrumentation.get("after") or []):
            errors.append(f"{prefix}.instrumentation_spec_id creates a circular closure dependency")
        descriptor_ref = raw["descriptor"]
        descriptor = None
        if not isinstance(descriptor_ref, str) or not descriptor_ref or descriptor_ref.startswith(("/", "~")) or ".." in Path(descriptor_ref).parts or "://" in descriptor_ref:
            errors.append(f"{prefix}.descriptor must be a safe relative path")
        elif load_descriptor is None:
            errors.append(f"{prefix}.descriptor cannot be validated because experiment protocol is unavailable")
        else:
            roots = [spec_file.parent, spec_file.parent.parent]
            path = next((root / descriptor_ref for root in roots if (root / descriptor_ref).is_file()), roots[-1] / descriptor_ref)
            try:
                descriptor = load_descriptor(path)
            except (ExperimentProtocolError, OSError) as exc:
                errors.append(f"{prefix}.descriptor is invalid: {exc}")
        if descriptor is not None:
            if descriptor.get("experiment_id") != raw["experiment_id"]:
                errors.append(f"{prefix}.experiment_id disagrees with descriptor")
            if descriptor.get("source_spec_id") != fm.get("id"):
                errors.append(f"{prefix}.descriptor does not backlink to source spec")
            hypotheses = {item["id"]: item for item in descriptor["hypotheses"]}
            hypothesis_ids = raw["hypothesis_ids"]
            if not isinstance(hypothesis_ids, list) or not hypothesis_ids:
                errors.append(f"{prefix}.hypothesis_ids must be a non-empty list")
            else:
                for hypothesis_id in hypothesis_ids:
                    hypothesis = hypotheses.get(hypothesis_id)
                    if hypothesis is None:
                        errors.append(f"{prefix}.hypothesis_ids contains unknown {hypothesis_id}")
                    elif live_id not in hypothesis["live_execution_ids"]:
                        errors.append(f"{prefix}.{live_id} is not mapped by hypothesis {hypothesis_id}")
    duplicates = sorted({item for item in mapped if mapped.count(item) > 1})
    if duplicates:
        errors.append("delegated live execution IDs must map exactly once: " + ", ".join(duplicates))
    if status == "done" and set(mapped) != unchecked:
        errors.append(
            "done delegated_experiment mappings must exactly cover unchecked live items; "
            f"unchecked={sorted(unchecked)}, mapped={sorted(set(mapped))}"
        )
    return errors


def fleet_uniqueness_findings(specs_dir: Path, spec_files: list[Path]) -> dict[str, list[str]]:
    """Return warning-only fleet ID collision findings for ``spec_files``.

    Fleet discovery remains owned by ``DependencyRegistryResolver``; the
    validator only consumes its shared enumeration.
    """
    parsed: list[tuple[Path, str, bytes]] = []
    for spec_file in spec_files:
        try:
            content = spec_file.read_bytes()
            fm = yaml.safe_load(content.decode("utf-8").split("\n---", 1)[0][3:]) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        if isinstance(fm, dict) and fm.get("id"):
            parsed.append((spec_file.resolve(), str(fm["id"]), content))

    findings = {path.name: [] for path, _, _ in parsed}
    if not parsed:
        return findings

    resolver = DependencyRegistryResolver(specs_dir, cache_seconds=0)
    records_by_id, registry_error = resolver.records_for(spec_id for _, spec_id, _ in parsed)

    # A flat specs directory without a registry is the normal standalone form;
    # retain its quiet behaviour. A managed .nightshift/specs directory expects
    # a sibling registry, so make that unavailable fleet check observable.
    registry_expected = specs_dir.parent.name == ".nightshift"
    if registry_error and (resolver.registry_path.is_file() or registry_expected):
        message = f"WARNING: fleet uniqueness check skipped, registry unavailable: {registry_error}"
        for path, _, _ in parsed:
            findings[path.name].append(message)
        return findings

    for path, spec_id, local_content in parsed:
        for record in records_by_id.get(spec_id, ()):
            if record.spec_path == path:
                continue
            try:
                other_content = record.spec_path.read_bytes()
            except OSError:
                continue
            if other_content != local_content:
                findings[path.name].append(
                    f"WARNING: spec id {spec_id} also exists in {record.spec_path} — not fleet-unique"
                )
    return findings


def parse_frontmatter_and_body(content: str) -> tuple[dict | None, str | None, list[str], int | None]:
    """Split a spec file's raw text into (frontmatter, body, errors, end_idx).

    Shared by ``validate_file`` (working-tree bytes) and SPEC-358's staged-index
    mode (``validate_staged``, index-blob bytes) so both read frontmatter and
    body identically instead of two independently drifting parsers.

    On error, ``fm``/``body``/``end_idx`` are ``None`` and ``errors`` is a
    single-item list matching ``validate_file``'s original early-return
    strings, so existing callers keep the exact same messages.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, None, ["missing opening frontmatter delimiter ('---')"], None

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None, None, ["missing closing frontmatter delimiter ('---')"], None

    fm_text = "\n".join(lines[1:end_idx])
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        return None, None, [f"invalid YAML frontmatter: {exc}"], None

    if not isinstance(fm, dict):
        return None, None, ["frontmatter must be a YAML mapping"], None

    body = "\n".join(lines[end_idx + 1:])
    return fm, body, [], end_idx


# ---------------------------------------------------------------------------
# SPEC-358 R1/R2/R5: shared static state-rationale validation.
#
# Reuses SPEC-357's parser/schema in ``lifecycle.py`` (``parse_state_rationale``,
# ``validate_state_rationale_mapping``, ``requires_state_rationale``,
# ``state_rationale_snapshots_equal``, ``terminal_statuses``,
# ``NONTERMINAL_LIFECYCLE_STATUSES_REQUIRING_TRIGGER``) rather than
# reimplementing them -- this module only adds the layer SPEC-357 explicitly
# deferred to SPEC-358: status/record cross-reference, snapshot equality
# against the referenced artifact, placeholder rejection, evidence-target
# resolution, path containment (R5), and the adoption severity matrix (R2).
# ---------------------------------------------------------------------------

# Literal strings copied verbatim from specs/_TEMPLATE.md's worked example.
# A spec that ships these unchanged has not actually written a rationale.
_STATE_RATIONALE_PLACEHOLDER_REASONS = {
    "why this specific status was chosen, not the enum's generic meaning.",
    # Documented generic enum-only reasons from lifecycle.derive_admission():
    # explaining the *mapping*, not the author's actual decision (SPEC-357 Problem).
    "explicitly planned for later",
    "draft specification",
    "all deterministic admission gates passed",
}
_STATE_RATIONALE_PLACEHOLDER_RECONSIDER = {
    "the concrete condition, decision, date, or review trigger that would change this status.",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_ANCHOR_SLUG_STRIP_RE = re.compile(r"[^\w\- ]")
_ANCHOR_SLUG_DASH_RE = re.compile(r"-+")


def _heading_slug(heading_text: str) -> str:
    """GitHub-style Markdown heading-to-anchor-slug (lowercase, dash-joined)."""
    slug = _ANCHOR_SLUG_STRIP_RE.sub("", heading_text.strip().lower())
    slug = slug.replace(" ", "-")
    return _ANCHOR_SLUG_DASH_RE.sub("-", slug).strip("-")


def resolve_markdown_anchor(text: str, anchor: str) -> bool:
    """R1/AC1: True if some Markdown heading in ``text`` slugifies to ``anchor``."""
    fenced = None
    seen = {}
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            marker = line.lstrip()[:3]
            if fenced is None:
                fenced = marker
            elif fenced == marker:
                fenced = None
            continue
        if fenced is not None:
            continue
        match = _HEADING_RE.match(line)
        if match:
            slug = _heading_slug(match.group(2))
            number = seen.get(slug, 0)
            seen[slug] = number + 1
            if (slug if number == 0 else f"{slug}-{number}") == anchor:
                return True
    return False


class PathEscapeError(ValueError):
    """R5: a locator/record path resolves outside its permitted root."""


def resolve_contained_path(root: Path, relative: str) -> Path:
    """R5: resolve ``relative`` under ``root``, refusing traversal/symlink escape.

    Normalizes and follows symlinks (``Path.resolve``) and then requires the
    real resolved path to be ``root`` itself or a real descendant of it.
    Raises :class:`PathEscapeError` otherwise -- never silently clamps.
    """
    root_real = Path(root).resolve()
    if not lifecycle.is_safe_relative_posix_path(relative):
        raise PathEscapeError(f"not a safe relative path: {relative!r}")
    candidate = root_real / relative
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_real)
    except ValueError:
        raise PathEscapeError(
            f"path escapes permitted root {root_real}: {relative!r} resolves to {resolved}"
        ) from None
    return resolved


def _state_rationale_placeholder_findings(mapping: dict) -> list[str]:
    findings = []
    reason = str(mapping.get("reason") or "").strip().lower()
    if reason in _STATE_RATIONALE_PLACEHOLDER_REASONS:
        findings.append(
            "state_rationale_placeholder_reason: reason is a template placeholder or a "
            "documented generic enum-only reason, not the actual decision"
        )
    reconsider = mapping.get("reconsider_when")
    if isinstance(reconsider, str) and reconsider.strip().lower() in _STATE_RATIONALE_PLACEHOLDER_RECONSIDER:
        findings.append(
            "state_rationale_placeholder_reconsider_when: reconsider_when is the template "
            "placeholder, not a concrete condition"
        )
    return findings


def validate_state_rationale_static(
    fm: dict,
    body: str,
    spec_file: Path,
    *,
    reports_root: Path | None = None,
    index_entries: list[dict] | None = None,
    read_text=None,
    report_legacy: bool = False,
    git_root: Path | None = None,
) -> list[str]:
    """SPEC-358 R1/AC1: static validation of the ``## State rationale`` section.

    ``read_text`` -- optional ``callable(Path) -> str``, used to resolve
    evidence-locator ``kind: file`` targets and the referenced artifact's
    JSON content. Defaults to a plain filesystem read. SPEC-358 R3's staged
    mode passes a reader bound to the Git index snapshot so this exact same
    function runs, unmodified, against staged bytes instead of working-tree
    bytes (single shared validation core, per R1).

    ``index_entries`` -- optional pre-fetched ``artifacts/index.json``
    ``entries`` list (also for staged mode, where the index itself may be an
    unmodified-but-tracked file). Defaults to ``spec_artifacts.read_index``
    (filesystem).

    Explicitly does **not** claim structural validity proves the reasoning is
    true (R1's own limit) -- a specific-but-false ``reason`` string still
    passes this function and remains a human/REVIEW concern.
    """
    if spec_file.name.startswith("_"):
        return []
    reader = read_text or (lambda path: Path(path).read_text(encoding="utf-8"))

    try:
        section = lifecycle.parse_state_rationale(body)
    except lifecycle.StateRationaleError as exc:
        return [f"state_rationale_malformed: {exc}"]

    if section is None:
        if not lifecycle.requires_state_rationale(fm):
            return []
        if isinstance(fm.get("template_version"), int) and fm["template_version"] >= 12:
            return ["state_rationale_required_missing: template version 12 requires a State rationale section"]
        # R2/Adoption modes: "only version/section opt-in is enforceable" for
        # a spec that has not opted in at all -- an absent section on a spec
        # that never adopted the contract is not itself a finding here; it is
        # a corpus-audit signal (LE2/R6 adoption counts, opt-in callers only).
        if report_legacy:
            return [
                "WARNING: state_rationale_legacy_missing: no '## State rationale' section "
                "(legacy; backfill required on next edit per SPEC-358 R2)"
            ]
        return []

    findings: list[str] = []
    try:
        mapping_errors = lifecycle.validate_state_rationale_mapping(section)
    except (TypeError, ValueError) as exc:
        mapping_errors = [f"invalid field types: {exc}"]
    for field in ("schema_version",):
        if type(section.get(field)) is not int:
            mapping_errors.append(f"{field} must be an integer")
    for locator in section.get("evidence", []) if isinstance(section.get("evidence"), list) else []:
        if isinstance(locator, dict):
            if any(not isinstance(value, str) or not value.strip() for value in locator.values()):
                mapping_errors.append("evidence locator fields must be nonblank strings")
    for error in mapping_errors:
        family = "state_rationale_schema"
        if error.startswith("reason "):
            family = "state_rationale_reason_invalid"
        elif error.startswith("reconsider_when "):
            family = "state_rationale_reconsider_required"
        findings.append(f"{family}: state_rationale_schema: {error}")
    if mapping_errors:
        # Missing/malformed fields make status/record cross-checks below
        # meaningless (e.g. no 'status' key at all) -- report the schema
        # findings alone rather than cascading confusing secondary errors.
        findings.extend(_state_rationale_placeholder_findings(section))
        return findings
    findings.extend(_state_rationale_placeholder_findings(section))

    fm_status = fm.get("status")
    section_status = section.get("status")
    if section_status != fm_status:
        findings.append(
            f"state_rationale_status_mismatch: section status {section_status!r} does not "
            f"match frontmatter status {fm_status!r} (R1: status binds to stored lifecycle "
            "value, never derived run_state)"
        )

    project_root = spec_file.parent.parent if spec_file.parent.name == "specs" else spec_file.parent
    evidence = section.get("evidence")
    if isinstance(evidence, list):
        for index, entry in enumerate(evidence):
            if entry.get("project") or entry.get("kind") == "url":
                findings.append(f"WARNING: state_rationale_unverified_external: evidence[{index}] availability was not checked")
                continue
            kind = entry.get("kind")
            raw_path = str(entry.get("path", ""))
            permitted_root = project_root
            if kind == "spec":
                candidates = []
                for candidate in sorted(spec_file.parent.glob("*.md")):
                    try:
                        candidate_fm, _, _, _ = parse_frontmatter_and_body(reader(candidate))
                        if candidate_fm and candidate_fm.get("id") == entry["id"]:
                            candidates.append(candidate)
                    except (OSError, KeyError):
                        pass
                if len(candidates) != 1:
                    findings.append(f"state_rationale_broken_evidence_link: evidence[{index}] spec {entry['id']!r} must resolve uniquely")
                    continue
                raw_path = candidates[0].relative_to(project_root).as_posix()
            elif kind == "artifact":
                if not lifecycle.is_safe_relative_posix_path(str(entry["spec"])) or "/" in str(entry["spec"]):
                    findings.append(f"state_rationale_evidence_path_escape: evidence[{index}] invalid artifact owner")
                    continue
                try:
                    local_reports = reports_root or resolve_contained_path(project_root, "reports")
                    permitted_root = resolve_contained_path(local_reports, str(entry["spec"]))
                    source_index = json.loads(reader(resolve_contained_path(permitted_root, "artifacts/index.json")))
                    indexed = source_index.get("entries", []) if isinstance(source_index, dict) else []
                    if not any(isinstance(item, dict) and item.get("path") == raw_path for item in indexed):
                        raise ValueError("target artifact is not indexed")
                except (OSError, KeyError, ValueError, TypeError):
                    findings.append(f"state_rationale_broken_evidence_link: evidence[{index}] artifact is not indexed in this snapshot")
                    continue
            elif kind == "git":
                repository = git_root or project_root
                if _run_git(repository, ["rev-parse", "--git-dir"]).returncode:
                    findings.append(f"WARNING: state_rationale_unverified_external: evidence[{index}] Git repository is unavailable")
                elif (_run_git(repository, ["cat-file", "-e", entry["commit"] + "^{commit}"]).returncode
                      or _run_git(repository, ["cat-file", "-t", entry["commit"] + ":" + raw_path]).stdout.strip() != "blob"):
                    findings.append(f"state_rationale_broken_evidence_link: evidence[{index}] Git commit/file does not exist locally")
                continue
            try:
                target = resolve_contained_path(permitted_root, raw_path)
            except PathEscapeError as exc:
                findings.append(f"state_rationale_evidence_path_escape: evidence[{index}]: {exc}")
                continue
            try:
                text = reader(target)
            except UnicodeDecodeError:
                # Binary local evidence is valid; only heading locators need text.
                text = ""
            except (OSError, KeyError):
                findings.append(
                    f"state_rationale_broken_evidence_link: evidence[{index}] file not found "
                    f"in this snapshot: {raw_path}"
                )
                continue
            anchor = entry.get("anchor")
            if anchor and not resolve_markdown_anchor(text, str(anchor)):
                findings.append(
                    f"state_rationale_broken_evidence_anchor: evidence[{index}] anchor "
                    f"{anchor!r} not found in {raw_path}"
                )

    record = section.get("record")
    if isinstance(record, str) and record.startswith("artifacts/"):
        spec_id = str(fm.get("id") or "")
        try:
            root = reports_root if reports_root is not None else resolve_contained_path(project_root, "reports")
            owner_root = resolve_contained_path(root, spec_id)
            artifact_root = resolve_contained_path(owner_root, "artifacts")
        except PathEscapeError as exc:
            return findings + [f"state_rationale_record_path_escape: {exc}"]
        try:
            index_file = resolve_contained_path(root, f"{spec_id}/artifacts/index.json")
            if index_entries is not None:
                entries = index_entries
            else:
                data = json.loads(reader(index_file))
                if (not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != 1
                        or data.get("spec_id") != spec_id or not isinstance(data.get("entries"), list)
                        or any(not isinstance(item, dict) for item in data["entries"])):
                    raise ValueError("invalid index schema, owner or entries")
                entries = data["entries"]
        except (OSError, KeyError):
            entries = []
        except (ValueError, TypeError) as exc:
            return findings + [f"state_rationale_index_malformed: {exc}"]
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            return findings + ["state_rationale_index_malformed: entries must be a list of mappings"]
        matching = [entry for entry in entries if entry.get("path") == record]
        if len(matching) > 1:
            findings.append("state_rationale_index_malformed: selected record has duplicate index entries")
        if not matching:
            findings.append(
                f"state_rationale_record_not_indexed: record {record!r} is not listed in "
                f"{spec_id}'s artifacts/index.json"
            )
        else:
            entry = matching[0]
            if entry.get("type") not in {"decision", "status-transition"}:
                findings.append(
                    f"state_rationale_record_wrong_type: indexed type {entry.get('type')!r} "
                    "is not a decision or status-transition record"
                )
            try:
                artifact_path = resolve_contained_path(
                    artifact_root, record.split("/", 1)[1]
                )
            except PathEscapeError as exc:
                findings.append(f"state_rationale_record_path_escape: {exc}")
                artifact_path = None
            if artifact_path is not None:
                try:
                    raw_content = reader(artifact_path)
                    content = json.loads(raw_content)
                except (OSError, KeyError, ValueError):
                    findings.append(f"state_rationale_record_unreadable: cannot read/parse {record}")
                else:
                    if not isinstance(content, dict) or content.get("spec_id") != spec_id or content.get("kind") != "spec_artifact":
                        findings.append("state_rationale_record_wrong_owner: selected record identity does not match this spec")
                    if not isinstance(content, dict) or content.get("type") != entry.get("type"):
                        findings.append("state_rationale_record_wrong_type: record type disagrees with index")
                    stored_snapshot = content.get("state_rationale") if isinstance(content, dict) else None
                    if not isinstance(stored_snapshot, dict):
                        findings.append("state_rationale_stale_snapshot: selected record has no rationale snapshot")
                    if isinstance(stored_snapshot, dict):
                        if not lifecycle.state_rationale_snapshots_equal(section, stored_snapshot):
                            findings.append(
                                f"state_rationale_stale_snapshot: {record}'s state_rationale "
                                "content does not match the current '## State rationale' section"
                            )
                        to_status = content.get("to") if isinstance(content, dict) else None
                        if content.get("type") == "status-transition" and to_status != section_status:
                            findings.append(
                                f"state_rationale_transition_target_mismatch: {record}'s "
                                f"transition target {to_status!r} does not equal section "
                                f"status {section_status!r}"
                            )

    return findings


def state_rationale_adoption_findings(
    fm: dict,
    body: str,
    *,
    baseline_fm: dict | None = None,
    baseline_body: str | None = None,
    is_new: bool | None = None,
    baseline_available: bool = True,
    bytes_changed: bool | None = None,
    strict: bool = False,
) -> list[str]:
    """SPEC-358 R2/AC2: the single documented severity/adoption matrix.

    ``baseline_fm``/``baseline_body`` are HEAD's frontmatter/body, or ``None``
    when the spec is absent from HEAD (new) or no baseline is available at
    all (``is_new`` disambiguates the two: pass it explicitly when the caller
    knows there is simply no Git baseline available, e.g. file/directory mode
    without Git, so an existing spec is not misreported as "new").

    ``baseline_available=False`` -- no Git repository or explicit baseline
    snapshot at all (e.g. plain ``validate_file``/``validate_directory``
    callers with no ``--baseline``). Per R2/the Adoption modes section: only
    version/section opt-in is enforceable in that mode; next-edit adoption
    ("this changed legacy spec needs backfill") is never claimed, since
    "changed relative to what?" has no answer without Git. A present,
    opted-in section still has its record requirement enforced -- that is
    the currently declared contract, not a legacy-adoption judgment.
    """
    if not fm.get("id") or not lifecycle.requires_state_rationale(fm):
        return []

    if not baseline_available:
        # R3/Adoption modes: "only version/section opt-in is enforceable...
        # report baseline_unavailable, never pretend to have checked 'next
        # edit' adoption." The baseline_unavailable marker itself belongs in
        # the caller's JSON envelope (R3), not as a per-spec finding emitted
        # on every validate_file() call -- so a spec that never opted in
        # (no template_version >= 12, no section) produces no finding at all
        # here. A spec that *did* opt in still gets its record requirement
        # enforced, since that is the currently declared contract, not a
        # legacy-adoption judgment.
        try:
            section = lifecycle.parse_state_rationale(body)
        except lifecycle.StateRationaleError:
            section = None
        if section is None:
            if strict or (isinstance(fm.get("template_version"), int) and fm["template_version"] >= 12):
                return ["state_rationale_required_missing: current state requires a shaped rationale"]
            return ["WARNING: state_rationale_legacy_missing: baseline_unavailable; next-edit adoption was not checked"]
        findings = []
        if section.get("record") is None and (strict or fm.get("status") != "draft"):
            findings.append(
                f"state_rationale_record_required: status {fm.get('status')!r} requires an "
                "indexed record, not record: null (R2)"
            )
        elif section.get("record") is None:
            findings.append("WARNING: state_rationale_record_pending: draft record may be authored before promotion")
        return findings

    def _try_parse(text: str | None) -> dict | None:
        if text is None:
            return None
        try:
            return lifecycle.parse_state_rationale(text)
        except lifecycle.StateRationaleError:
            return None  # already reported by validate_state_rationale_static

    section = _try_parse(body)
    baseline_section = _try_parse(baseline_body)

    def _opted_in(frontmatter: dict, parsed_section: dict | None) -> bool:
        template_version = frontmatter.get("template_version")
        return (isinstance(template_version, int) and template_version >= 12) or parsed_section is not None

    opted_in = _opted_in(fm, section)
    if is_new is None:
        is_new = baseline_fm is None

    findings: list[str] = []

    if baseline_fm is not None and not is_new:
        baseline_opted_in = _opted_in(baseline_fm, baseline_section)
        if baseline_opted_in and not opted_in:
            findings.append(
                "state_rationale_adoption_regressed: HEAD already has template_version >= 12 "
                "or a '## State rationale' section; removing/lowering it is not permitted"
            )
        base_tv, cur_tv = baseline_fm.get("template_version"), fm.get("template_version")
        if baseline_opted_in and isinstance(base_tv, int) and isinstance(cur_tv, int) and cur_tv < base_tv:
            findings.append(
                f"state_rationale_adoption_regressed: template_version lowered from "
                f"{base_tv} to {cur_tv} cannot bypass an already-adopted contract"
            )

    status = fm.get("status")

    if is_new:
        # A spec absent from HEAD is new regardless of its claimed template_version.
        if section is None:
            findings.append(
                "state_rationale_required_missing: new spec has no '## State rationale' section"
            )
        elif section.get("record") is None:
            if status == "draft":
                findings.append(
                    "WARNING: state_rationale_record_pending: new draft spec has a shaped "
                    "rationale but record is still null; a record is required before "
                    "admission to planned/ready (R2)"
                )
            else:
                findings.append(
                    f"state_rationale_record_required: new spec with status {status!r} "
                    "requires an indexed record, not record: null (R2: new planned/ready/"
                    "in_progress/blocked/terminal states all require a matching record)"
                )
        return findings

    changed = bytes_changed if bytes_changed is not None else baseline_fm != fm or baseline_body != body
    baseline_status = baseline_fm.get("status") if baseline_fm else None
    was_terminal = baseline_status in lifecycle.terminal_statuses() if baseline_fm else False

    if not opted_in:
        if not changed:
            return [
                "WARNING: state_rationale_legacy_missing: unchanged pre-adoption spec, no "
                "section (legacy; backfill on next edit per R2)"
            ]
        if was_terminal and status == baseline_status and baseline_body == body:
            # Metadata-only edit to an already-terminal legacy spec: R2 says
            # this must not fabricate a past decision -- stays exempt/warning.
            return [
                "WARNING: state_rationale_legacy_missing: metadata-only edit to an "
                "already-terminal legacy spec (no fabricated history required, R2)"
            ]
        findings.append(
            "state_rationale_adoption_required: this changed legacy spec has no "
            "'## State rationale' section; R2 requires backfill on the next edit of any "
            "changed nonterminal-or-newly-terminal legacy spec (a new terminal transition "
            "is not a grandfathering escape)"
        )
        return findings

    if section is None:
        findings.append(
            "state_rationale_required_missing: changed spec has no '## State rationale' section"
        )
        return findings
    if section.get("record") is None and status != "draft":
        findings.append(
            f"state_rationale_record_required: status {status!r} requires an indexed record, "
            "not record: null (R2)"
        )
    return findings


def validate_file(spec_file: Path, config_path: Path | None = None, all_specs: list[dict] | None = None, *, check_adoption: bool = True, base_revision: str = "HEAD", git_root: Path | None = None) -> list:
    """Return a list of error/warning strings for spec_file, or [] if valid.

    Items prefixed 'WARNING: ' are non-fatal — they appear in output but do not
    set a non-zero exit code. All other items are errors.

    ``config_path`` — explicit path to the project's ``config.yaml``.  When
    omitted, the validator looks for ``config.yaml`` two directories above the
    spec file (i.e. ``spec_file.parent.parent / "config.yaml"``), which is the
    standard Nightshift layout (``.nightshift/specs/<SPEC>.md`` → ``.nightshift/
    config.yaml``).  Pass an explicit path in tests to stay deterministic.
    """
    errors = []

    # Resolve config_path for the kit_version gate (R1/R3).
    if config_path is None:
        config_path = spec_file.parent.parent / "config.yaml"

    try:
        content = spec_file.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read file: {exc}"]

    fm, body, parse_errors, end_idx = parse_frontmatter_and_body(content)
    if parse_errors:
        return parse_errors
    lines = content.split("\n")
    fm_text = "\n".join(lines[1:end_idx])
    first_h1 = None
    for line in body.split("\n"):
        if line.startswith("# "):
            first_h1 = line[2:].strip()
            break
    if first_h1 is None:
        errors.append("missing body H1 title ('# ...'); board cards need a display title")
    elif first_h1.lower() == "block reason":
        errors.append(
            "first body H1 is 'Block Reason', so the board title will be wrong; "
            "put the real spec title first and use '## Block Reason' for blocker details"
        )

    # SPEC-163: a full brief is opt-in for material REVIEW cases.  It is stored
    # in the existing QUESTIONS document, while the source spec only keeps the
    # resolved constraint and a backlink.
    if str(fm.get("type", "")).lower() == "questions" or _DECISION_BRIEF_HEADING.search(body):
        project_root = spec_file.parent.parent if spec_file.parent.name == "specs" else spec_file.parent
        errors.extend(validate_decision_briefs(body, project_root))
    errors.extend(validate_report_action_log(body))
    errors.extend(validate_reuse_gate(body))
    errors.extend(validate_ac_amendments(content, spec_file))
    errors.extend(validate_scope(fm))
    errors.extend(validate_scope_amendments(body))
    errors.extend(validate_resolved_blocker_fields(fm))
    # R8: a ready code spec with neither scope: nor touches: silently gets
    # the project-root default — surface that as a warning, never an error,
    # so historical specs are not retroactively required to declare either.
    if (
        fm.get("status") == "ready"
        and str(fm.get("type", "")).lower() in {"feature", "bugfix", "refactor"}
        and fm.get("scope") is None
        and not fm.get("touches")
    ):
        errors.append(
            "WARNING: no scope: or touches: declared; the project-root default write scope will apply"
        )

    # Required fields
    if "id" not in fm:
        errors.append("missing required field: id")
    if "status" not in fm:
        errors.append("missing required field: status")
    else:
        status = fm["status"]
        if not isinstance(status, str):
            errors.append(f"status must be a string, got {type(status).__name__!r}")
        else:
            status_error = status_error_for_spec(fm, status)
            if status_error:
                errors.append(status_error)
            if status == "planning":
                target, result = migrate_legacy_planning(fm)
                if target:
                    errors.append(
                        f"legacy status 'planning' must migrate deterministically to '{target}'"
                    )
                else:
                    errors.append(
                        "legacy status 'planning' requires REVIEW: " + "; ".join(result.findings)
                    )
            errors.extend(validate_blocked(fm))

    canonical = Path(__file__).resolve().parent
    manifest_path = canonical / "release-manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
            errors.extend(release_handoff.validate_spec_handoff(fm, canonical, manifest))
        except (json.JSONDecodeError, OSError):
            errors.append("release handoff validation could not read canonical manifest")

    # A done spec must have all checkboxes checked in Requirements and
    # Acceptance Criteria sections — unchecked boxes in those sections mean
    # requirements or ACs were never completed. Other sections (e.g. Live
    # Execution Checklist) may legitimately have open items post-merge.
    if fm.get("status") == "done":
        _checked_sections = {
            "## Requirements": "Requirements",
            "## Acceptance Criteria": "Acceptance Criteria",
        }
        _current_section = None
        _unchecked_findings = []
        for line_number, line in enumerate(lines[end_idx + 1:], start=end_idx + 2):
            if line.startswith("## "):
                _current_section = _checked_sections.get(line.strip())
            elif _current_section and re.match(r"^\s*- \[ \]", line):
                _unchecked_findings.append({
                    "line": line_number,
                    "section": _current_section,
                    "text": line.strip(),
                })
        _disposition = _historical_checkbox_disposition(spec_file, _unchecked_findings)
        if _disposition:
            errors.append(
                "WARNING: historical checkbox/status residual documented in "
                f"{_HISTORICAL_CHECKBOX_DISPOSITIONS}: {_disposition} "
                f"({len(_unchecked_findings)} unchecked item(s)); "
                "implementation status is not inferred"
            )
        else:
            for _finding in _unchecked_findings:
                errors.append(
                    f"{spec_file}:{_finding['line']}: status is 'done' but has an unchecked "
                    f"checkbox in {_finding['section']}: {_finding['text']}"
                )
    errors.extend(validate_real_use_evidence(fm, lines[end_idx + 1:], spec_file, all_specs))

    # SPEC-358 R1: static state-rationale validation runs in file mode too
    # (previously only reachable indirectly through directory mode).
    errors.extend(validate_state_rationale_static(fm, body, spec_file, git_root=git_root))
    if check_adoption and not spec_file.name.startswith("_"):
        baseline = _working_baseline(spec_file, base_revision)
        base_text, available = baseline
        base_fm, base_body, _, _ = parse_frontmatter_and_body(base_text) if base_text is not None else (None, None, [], None)
        errors.extend(state_rationale_adoption_findings(
            fm, body, baseline_fm=base_fm, baseline_body=base_body,
            baseline_available=available, is_new=available and base_text is None,
            bytes_changed=base_text != content,
        ))

    # SPEC-358 R1: single-file validation now also executes the artifact
    # directory sweep (SPEC-291 R6) that previously only ran in
    # validate_directory(). A spec with no artifacts/ directory still
    # produces no findings (SPEC-291 R7: absence is never a finding).
    if fm.get("id"):
        try:
            install_root = spec_file.parent.parent if spec_file.parent.name == "specs" else spec_file.parent
            checked_reports = resolve_contained_path(install_root, "reports")
            resolve_contained_path(checked_reports, str(fm["id"]) + "/artifacts")
        except PathEscapeError as exc:
            errors.append(f"state_rationale_record_path_escape: {exc}")
        else:
            errors.extend(spec_artifacts.validate_artifact_index(checked_reports, str(fm["id"])))

    attachments = fm.get("attachments")
    if attachments is not None:
        if not isinstance(attachments, list):
            errors.append("attachments must be a list of mappings")
        else:
            for idx, item in enumerate(attachments):
                prefix = f"attachments[{idx}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} must be a mapping")
                    continue
                path = item.get("path")
                description = item.get("description")
                if not isinstance(path, str) or not path.strip():
                    errors.append(f"{prefix}.path is required and must be a non-empty string")
                if not isinstance(description, str) or not description.strip():
                    errors.append(f"{prefix}.description is required and must be a non-empty string")
                for optional_key in ("kind", "role"):
                    value = item.get(optional_key)
                    if value is not None and not isinstance(value, str):
                        errors.append(f"{prefix}.{optional_key} must be a string when present")

    # Shared fields used by SPEC-065 and SPEC-066 checks below
    _spec_type = str(fm.get("type", "")).lower()
    _spec_status = str(fm.get("status", "")).lower()
    _spec_id = str(fm.get("id", ""))
    _is_nfr = _spec_id.startswith("NFR-") or _spec_type == "nfr"

    # SPEC-236: ordinary specs intentionally have no synthetic parentage.  A
    # newly-created follow-up opts into this compact, auditable backlink; its
    # lineage evidence stays in the ignored metrics surface rather than being
    # copied into mutable spec prose.
    followup = fm.get("followup")
    if followup is not None:
        if not isinstance(followup, dict):
            errors.append("followup must be a mapping")
        else:
            allowed = {"source_spec_id", "lineage_record", "outcome"}
            for key in sorted(set(followup) - allowed):
                errors.append(f"followup.{key} is not allowed")
            source_id = followup.get("source_spec_id")
            if not isinstance(source_id, str) or not source_id.strip():
                errors.append("followup.source_spec_id must be a non-empty string")
            elif source_id == _spec_id:
                errors.append("followup.source_spec_id may not self-reference")
            else:
                corpus = all_specs if all_specs is not None else _load_directory_frontmatters(spec_file.parent)
                if source_id not in {str(candidate.get("id", "")) for candidate in corpus}:
                    errors.append("followup.source_spec_id does not resolve")
            reference = followup.get("lineage_record")
            if not isinstance(reference, str) or not reference.strip():
                errors.append("followup.lineage_record must be a non-empty relative path")
            elif reference.startswith(("/", "~")) or ".." in Path(reference).parts or "://" in reference:
                errors.append("followup.lineage_record must be a safe relative path")
            outcome = followup.get("outcome")
            if outcome != "created":
                errors.append("followup.outcome must be 'created' when a child spec exists")

    # SPEC-210 — absence is counted as ``unclassified`` by the derived summary,
    # never made a validation error or an implicit promotion refusal. A declared
    # malformed gap is surfaced early.
    if _spec_status == "draft":
        gap = fm.get("promotion_gap")
        if gap is not None and not isinstance(gap, dict):
            errors.append("promotion_gap must be a mapping with kind and reason")
        elif isinstance(gap, dict):
            kind = gap.get("kind")
            reason = gap.get("reason")
            if kind not in PROMOTION_GAP_KINDS:
                errors.append("promotion_gap kind must be one of: " + ", ".join(sorted(PROMOTION_GAP_KINDS)))
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"promotion_gap {kind} requires a non-empty reason")
            if kind == "awaiting_upstream_spec" and not str(gap.get("upstream_spec", "")).strip():
                errors.append("promotion_gap awaiting_upstream_spec requires upstream_spec")

    # SPEC-140: the declaration must be truthful when a mechanically matching
    # active NFR exists. Drafts stay authorable (warning); ready+ is a gate.
    if not _is_nfr and _spec_status in {"draft", "ready", "in_progress", "blocked"}:
        corpus = all_specs if all_specs is not None else _load_directory_frontmatters(spec_file.parent)
        active_nfrs = [
            candidate for candidate in corpus
            if is_nfr_family(candidate) and str(candidate.get("status", "")).lower() == "active"
        ]
        for nfr in active_nfrs:
            reasons = nfr_match_reasons(fm, nfr)
            if reasons and not nfr_is_bound_or_waived(fm, nfr):
                message = (
                    f"NFR reconciliation required: {_spec_id} matches {nfr.get('id')} "
                    f"via {', '.join(reasons)} but neither binds nor waives it"
                )
                errors.append(f"WARNING: {message}" if _spec_status == "draft" else message)

    waivers = fm.get("nfr_waivers")
    if waivers is not None:
        if not isinstance(waivers, list):
            errors.append("nfr_waivers must be a list of mappings")
        else:
            for index, waiver in enumerate(waivers):
                prefix = f"nfr_waivers[{index}]"
                if not isinstance(waiver, dict):
                    errors.append(f"{prefix} must be a mapping")
                    continue
                if not isinstance(waiver.get("id"), str) or not waiver["id"].strip():
                    errors.append(f"{prefix}.id is required and must be a non-empty string")
                if not isinstance(waiver.get("reason"), str) or not waiver["reason"].strip():
                    errors.append(f"{prefix}.reason is required and must be a non-empty string")

    # SPEC-307 R1: optional `execution:` model-override declaration. Absent
    # means "parent default" — no error. When present, only `worker_model`/
    # `verifier_model` are recognized, each a non-empty string; anything else
    # (unknown key or non-string value) is a WARN at draft and an ERROR at
    # ready+, matching the nfrs/promotion_gap severity-by-status pattern above.
    execution = fm.get("execution")
    if execution is not None:
        if not isinstance(execution, dict):
            message = "execution must be a mapping with worker_model and/or verifier_model"
            errors.append(f"WARNING: {message}" if _spec_status == "draft" else message)
        else:
            for key, value in execution.items():
                if key not in {"worker_model", "verifier_model"}:
                    message = f"execution has unknown key: {key!r} (only worker_model, verifier_model are recognized)"
                    errors.append(f"WARNING: {message}" if _spec_status == "draft" else message)
                elif not isinstance(value, str) or not value.strip():
                    message = f"execution.{key} must be a non-empty string"
                    errors.append(f"WARNING: {message}" if _spec_status == "draft" else message)

    # SPEC-065: nfrs: field required for feature/bugfix/refactor specs
    if _spec_type in _NFRS_REQUIRED_TYPES and "nfrs" not in fm:
        if _spec_status == "ready":
            errors.append(
                "missing required field: nfrs — feature/bugfix/refactor specs must declare "
                "nfrs: [] (reviewed, none apply) or list applicable NFR IDs before status: ready"
            )
        elif _spec_status == "draft":
            errors.append(
                "WARNING: missing nfrs field — add nfrs: [] or applicable NFR IDs "
                "before promoting to status: ready"
            )

    # SPEC-066: scope_tags: must be a list of strings when present on NFR-family specs
    scope_tags = fm.get("scope_tags")
    if scope_tags is not None and _is_nfr:
        if not isinstance(scope_tags, list):
            errors.append("scope_tags must be a list of strings")
        else:
            for _i, _tag in enumerate(scope_tags):
                if not isinstance(_tag, str):
                    errors.append(
                        f"scope_tags[{_i}] must be a string, got {type(_tag).__name__!r}"
                    )

    # SPEC-290: transfer_refusal, when present, must be a non-empty scalar
    # string — same shape as block_reason. No closed schema requires this
    # field at all; this only guards its shape when a writer sets it.
    transfer_refusal = fm.get("transfer_refusal")
    if transfer_refusal is not None:
        if not isinstance(transfer_refusal, str) or not transfer_refusal.strip():
            errors.append(
                "transfer_refusal must be a non-empty string when present "
                "— clear it by removing the field, not by setting it to ''"
            )

    # SPEC-071 (R9 b/c/d/e/f): portable path-variable hygiene over the WHOLE file
    # (frontmatter + prose). Code fences/spans are skipped by the detectors.
    # (d) Unquoted {{ }} frontmatter values.
    for line in _detect_unquoted_yaml_token(fm_text):
        errors.append(
            f"unquoted {{{{ }}}} token in frontmatter value: {line!r} "
            "— wrap path-var tokens in quotes"
        )
    # (e) Unknown template tokens (not a known UPPER path-var or lower prompt var).
    for tok in _detect_unknown_tokens(content):
        errors.append(
            f"unknown template token {tok} — expected a known path-var "
            f"({', '.join(sorted(_ANCHOR_NAMES))}) or a lower_snake prompt var "
            "(escape a literal in a code span)"
        )
    # (f) `..` traversal past PROJECT_ROOT.
    for tok in _detect_traversal(content):
        errors.append(
            f"path token {tok} traverses past PROJECT_ROOT with '..' "
            "— route cross-project references by spec name, not path arithmetic"
        )
    # (b/c) Residual absolute host/VM path leaks in prose/frontmatter.
    # Severity is config-driven (R1): ERROR when the project's kit_version is
    # at or above PROSE_ERROR_KIT_VERSION; WARNING during the transition period
    # so unmigrated projects aren't hard-blocked before the migration runs.
    # A missing/unreadable config or absent kit_version always defaults to
    # WARNING (R3) — never crash validation.
    _kit_ver = _read_kit_version(config_path)
    _prose_is_error = _kit_version_gte(_kit_ver, PROSE_ERROR_KIT_VERSION)
    for leak in _detect_leak_paths(content):
        msg = (
            f"absolute path leak {leak!r} — replace with a portable "
            "{{ANCHOR}}-relative token (run the SPEC-071 prose migration tool)"
        )
        errors.append(msg if _prose_is_error else f"WARNING: {msg}")

    # SPEC-294 AC1: a deploy_environment: naming an undeclared environment
    # is a named validation finding. Only meaningful when the project has
    # opted into a deployment: block at all (R2 zero-behavior-change).
    deploy_environment = fm.get("deploy_environment")
    if deploy_environment is not None:
        try:
            _deploy_cfg_raw = config_path.read_text(encoding="utf-8")
            _deploy_cfg = {}
            for _document in yaml.safe_load_all(_deploy_cfg_raw):
                if isinstance(_document, dict):
                    _deploy_cfg.update(_document)
        except (OSError, yaml.YAMLError):
            _deploy_cfg = {}
        if "deployment" in _deploy_cfg:
            _on_completion, _deploy_findings = resolve_deployment_policy(
                _deploy_cfg, str(deploy_environment)
            )
            for finding in _deploy_findings:
                errors.append(f"deploy_environment: {finding}")

    return errors


def validate_registry_file(registry_path: Path) -> list:
    """SPEC-071 R9a: validate a projects-registry.json file.

    ERROR (not WARN) if any project ``path`` is an absolute path matching a known
    anchor/home-style prefix or a ``.claude/worktrees/`` checkout. The registry is
    auto-fixed by ``write_projects_registry`` regeneration, so being strict is
    safe. Tokenized (``{{ARGO_HOME}}/...``) paths pass.
    """
    errors: list[str] = []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read registry: {exc}"]
    projects = data.get("projects", []) if isinstance(data, dict) else []
    for proj in projects:
        if not isinstance(proj, dict):
            continue
        path = proj.get("path")
        if not isinstance(path, str):
            continue
        # A tokenized path is the correct, portable form.
        if path.startswith("{{"):
            continue
        leaks = any(path.startswith(root) for root in _LEAK_ROOTS)
        worktree = ".claude/worktrees/" in path
        if leaks or worktree or path.startswith("/"):
            errors.append(
                f"registry path for project {proj.get('name', '?')!r} is a "
                f"non-portable absolute path {path!r} — regenerate the registry "
                "(nightshift-sync) to emit an {{ARGO_HOME}}-relative token"
            )
    return errors


def validate_config_file(config_path: Path) -> list:
    """SPEC-080: validate the ``board_column_defaults`` section of a config.yaml.

    Returns a list of finding strings.  Findings are prefixed ``WARNING: ``
    (matching the SPEC-078 runtime severity convention: the board warns and
    falls back rather than refusing to start).  An empty list means the section
    is absent or valid.
    """
    findings: list = []
    try:
        raw = config_path.read_text(encoding="utf-8")
        cfg = {}
        for document in yaml.safe_load_all(raw):
            if isinstance(document, dict):
                cfg.update(document)
    except Exception as exc:
        findings.append(f"WARNING: could not read config.yaml: {exc}")
        return findings

    if not isinstance(cfg, dict):
        return findings  # not a mapping — other validators handle this

    override = cfg.get("board_column_defaults")
    if override is not None:
        problems = _check_column_override(override)
        for problem in problems:
            findings.append(f"WARNING: board_column_defaults: {problem}")

    # SPEC-294 R1/R5: deployment: is a merge-safety gate, not a UI
    # preference, so unlike board_column_defaults its findings are errors
    # (no WARNING: prefix) -- they must not be silently non-fatal.
    findings.extend(deployment_block_findings(cfg))

    return findings


def _spec_status_by_file(specs_dir: Path) -> list[tuple[Path, str, str]]:
    """(path, id, status) for every non-template spec whose frontmatter parses."""
    rows = []
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8").split("\n---", 1)[0][3:]) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(parsed, dict) and parsed.get("id"):
            rows.append((path, str(parsed["id"]), str(parsed.get("status", "draft"))))
    return rows


def delivered_but_not_closed_findings(specs_dir: Path) -> dict[str, list[str]]:
    """SPEC-332 R4: a spec whose release handoff is ``completed`` was
    implemented, merged and shipped; any status other than ``done`` is an
    inconsistency between two records the kit owns. Keyed by spec file name."""
    canonical_root = specs_dir.parent
    findings: dict[str, list[str]] = {}
    for path, spec_id, status in _spec_status_by_file(specs_dir):
        if status == "done":
            continue
        artifact = release_handoff.artifact_path(canonical_root, spec_id)
        if not artifact.is_file():
            continue
        try:
            record = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("status") == "completed":
            findings.setdefault(path.name, []).append(
                f"release handoff completed ({record.get('target_version', '?')}) but spec status "
                f"is '{status}': close the spec or retire the handoff"
            )
    return findings


def status_sync_findings(specs_dir: Path, status_store_path: Path) -> dict[str, list[str]]:
    """SPEC-332 R3: the board's effective status must equal the file's status;
    compare the durable store to every spec file offline, without the board.
    An unopenable store is its own error, never a pass."""
    from status_store import StatusStore, classify_status_sync

    rows = _spec_status_by_file(specs_dir)
    findings: dict[str, list[str]] = {}
    try:
        store = StatusStore(Path(status_store_path))
        states = store.get_states([spec_id for _path, spec_id, _status in rows])
    except Exception as exc:  # noqa: BLE001 - report, never silently pass
        findings[str(status_store_path)] = [f"status-sync mismatch check could not open status store: {exc}"]
        return findings
    for path, spec_id, status in rows:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        found = classify_status_sync(status, states.get(spec_id), mtime, path)
        if found is not None:
            findings.setdefault(path.name, []).append(
                f"status-sync mismatch: file says '{status}', durable store says "
                f"'{found['durable']}' ({found['reason']}); the board shows '{found['effective']}'"
            )
    return findings


def validate_directory(specs_dir: Path, status_store_path: Path | None = None, *, base_revision: str = "HEAD") -> dict:
    """Validate all .md files in specs_dir. Returns {filename: [errors]}."""
    if not specs_dir.is_dir():
        raise ValueError(f"not a directory: {specs_dir}")

    results = {}
    all_specs = _load_directory_frontmatters(specs_dir)
    for spec_file in sorted(specs_dir.glob("*.md")):
        if spec_file.name.startswith("_"):
            continue  # skip template files
        results[spec_file.name] = validate_file(spec_file, all_specs=all_specs, base_revision=base_revision)

    # SPEC-332 R4 / R3.
    for name, findings in delivered_but_not_closed_findings(specs_dir).items():
        results.setdefault(name, []).extend(findings)
    if status_store_path is not None:
        for name, findings in status_sync_findings(specs_dir, status_store_path).items():
            results.setdefault(name, []).extend(findings)

    fleet_findings = fleet_uniqueness_findings(
        specs_dir,
        [path for path in sorted(specs_dir.glob("*.md")) if not path.name.startswith("_")],
    )
    for name, warnings in fleet_findings.items():
        results.setdefault(name, []).extend(warnings)

    # SPEC-252: the per-spec pass above can only reach an artifact a spec
    # declares.  Sweep the sibling handoff directory from the artifact side so
    # an orphaned or untracked artifact is reported against its own path
    # instead of being invisible.  Only artifacts with findings get a key, so a
    # clean directory does not inflate the validated-file count.
    canonical_root = specs_dir.parent
    for name, findings in release_handoff.sweep_handoff_directory(
        canonical_root,
        declaring_handoff_spec_ids(all_specs),
        tracked_paths=handoff_tracked_paths(canonical_root),
    ).items():
        results.setdefault(name, []).extend(findings)

    # SPEC-251 R3: the stranded backlog cannot silently regrow. A stranded
    # record must carry a recorded disposition (re-pin, fold, or retire);
    # this never suppresses release_handoff.validate_artifact's own
    # STRANDED_PENDING_HANDOFF_ERROR (R4) -- it is an additional, independent
    # finding against the artifact's own path.
    manifest_path = canonical_root / "release-manifest.json"
    if manifest_path.is_file():
        try:
            live_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            live_manifest = None
        if isinstance(live_manifest, dict):
            for name, findings in release_handoff.stranded_disposition_findings(
                canonical_root, live_manifest
            ).items():
                results.setdefault(name, []).extend(findings)

    # SPEC-272: extend the same artifact-side sweep to reports/ and runs/,
    # the two other directories populated by runs and referenced from specs
    # only by convention. Reachability rules live in artifact_reachability.py.
    corpus_spec_ids = all_corpus_spec_ids(all_specs)
    for name, findings in artifact_reachability.sweep_reports_directory(
        canonical_root,
        corpus_spec_ids,
        tracked_paths=reports_tracked_paths(canonical_root),
    ).items():
        results.setdefault(name, []).extend(findings)
    for name, findings in artifact_reachability.sweep_runs_directory(
        canonical_root,
        corpus_spec_ids,
        tracked_paths=runs_tracked_paths(canonical_root),
    ).items():
        results.setdefault(name, []).extend(findings)

    # SPEC-291 R6: validate every spec's artifacts/index.json (schema,
    # on-registry types, listed-file existence/tracking, orphan files). A
    # spec with no artifacts/ directory produces no findings (R7: absence of
    # historical artifacts is never retroactively required).
    reports_root = canonical_root / artifact_reachability.REPORTS_DIR
    tracked = reports_tracked_paths(canonical_root)
    for spec_file in sorted(specs_dir.glob("*.md")):
        if spec_file.name.startswith("_"):
            continue
        try:
            fm = yaml.safe_load(spec_file.read_text(encoding="utf-8").split("\n---", 1)[0][3:]) or {}
        except (OSError, yaml.YAMLError):
            continue
        spec_id = str(fm.get("id") or "") if isinstance(fm, dict) else ""
        if not spec_id:
            continue
        if any("state_rationale_record_path_escape" in finding for finding in results.get(spec_file.name, [])):
            continue
        artifact_findings = spec_artifacts.validate_artifact_index(
            reports_root, spec_id, tracked_paths=tracked,
        )
        if artifact_findings:
            results.setdefault(spec_file.name, []).extend(artifact_findings)

    # SPEC-071 R9a: validate the sibling projects-registry.json when present
    # (specs_dir is typically `.nightshift/specs`; the registry is its sibling).
    registry = specs_dir.parent / "projects-registry.json"
    if registry.is_file():
        registry_findings = validate_registry_file(registry)
        # A sibling registry is infrastructure for this directory's optional
        # fleet signal.  Its unreadability has already been reported against
        # each affected spec by ``fleet_uniqueness_findings`` as a warning, so
        # do not turn that degraded validation path into a CLI failure here.
        # Direct callers of ``validate_registry_file`` retain its strict parse
        # error and all valid-but-unsafe registry findings stay fatal.
        if not (
            len(registry_findings) == 1
            and registry_findings[0].startswith("cannot read registry: ")
        ):
            results[registry.name] = registry_findings

    # SPEC-080: validate the sibling config.yaml board_column_defaults when present.
    config_yaml = specs_dir.parent / "config.yaml"
    if config_yaml.is_file():
        results[config_yaml.name] = validate_config_file(config_yaml)

    return results


def _is_warning(msg: str) -> bool:
    return msg.startswith("WARNING: ")


def _render_text(
    results: dict,
    source: str,
    *,
    paths_examined: int = 1,
    per_path: list[tuple[str, dict]] | None = None,
) -> str:
    """Render validation results as human-readable text."""
    lines = []
    error_count = sum(
        sum(1 for e in errs if not _is_warning(e)) for errs in results.values()
    )
    warning_count = sum(
        sum(1 for e in errs if _is_warning(e)) for errs in results.values()
    )
    file_count = len(results)
    bad_count = sum(
        1 for errs in results.values() if any(not _is_warning(e) for e in errs)
    )

    if error_count == 0 and warning_count == 0:
        if paths_examined == 1:
            lines.append(f"[nightshift validate-specs] OK — {file_count} spec(s) valid")
        else:
            lines.append(
                f"[nightshift validate-specs] OK — {paths_examined} path(s) examined; "
                f"{file_count} spec(s) valid"
            )

    elif error_count == 0:
        lines.append(
            f"[nightshift validate-specs] OK (with {warning_count} warning(s)) "
            f"— {file_count} spec(s) checked"
        )
    else:
        prefix = (
            f"{paths_examined} path(s) examined; " if paths_examined != 1 else ""
        )
        lines.append(
            f"[nightshift validate-specs] FAILED — {prefix}{bad_count}/{file_count} spec(s) have errors"
        )
    if paths_examined != 1 and per_path is not None:
        lines.append("  paths:")
        for path, path_results in per_path:
            invalid = any(
                not _is_warning(error)
                for errors in path_results.values()
                for error in errors
            )
            state = "errors" if invalid else "valid"
            lines.append(f"    - {path}: {state} ({len(path_results)} spec(s))")
    for fname, errs in results.items():
        actual_errors = [e for e in errs if not _is_warning(e)]
        actual_warnings = [e[len("WARNING: "):] for e in errs if _is_warning(e)]
        if actual_errors or actual_warnings:
            lines.append(f"  {fname}:")
            for err in actual_errors:
                lines.append(f"    - {err}")
            for warn in actual_warnings:
                lines.append(f"    ~ {warn}")
    return "\n".join(lines)


def _collect_frontmatters_for_paths(positional: list[str]) -> list[dict]:
    """Shared frontmatter collection for --promotion-gap-summary and
    --ownership-summary — both need the whole examined corpus, not just one
    file's own frontmatter."""
    frontmatters: list[dict] = []
    for raw_path in positional:
        path = Path(raw_path)
        if path.is_dir():
            frontmatters.extend(_load_directory_frontmatters(path))
        elif path.is_file() and path.suffix == ".md":
            try:
                frontmatters.append(parse_spec_file(path).frontmatter)
            except FrontmatterError:
                pass
    return frontmatters


class StagedValidationError(RuntimeError):
    """SPEC-358 R3: the staged-index snapshot cannot be validated as-is."""


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Read-only Git plumbing only -- never checkout/stash/read-tree (R3)."""
    return subprocess.run(
        ["git", "-C", str(repo_root)] + list(args),
        capture_output=True, text=True,
    )


def git_has_head(repo_root: Path) -> bool:
    """R3: a brand-new repo with no HEAD gets an empty baseline, not an error."""
    return _run_git(repo_root, ["rev-parse", "--verify", "-q", "HEAD"]).returncode == 0


def staged_index_entries(repo_root: Path) -> dict[str, dict[str, str]]:
    """R3: the full tracked-index snapshot -- path -> {mode, sha}.

    This is the *whole* index (``git ls-files --stage``), not only this
    commit's changed paths: an unmodified-but-tracked file (e.g. an
    untouched ``artifacts/index.json``) must still be read from its current
    index entry, not from the working tree, so index/worktree hashes stay
    identical before and after validation (AC3). NUL-safe (``-z``) so paths
    with spaces/newlines round-trip correctly (R4). Raises
    :class:`StagedValidationError` on any unresolved (unmerged) entry.
    """
    result = _run_git(repo_root, ["ls-files", "--stage", "-z"])
    if result.returncode != 0:
        raise StagedValidationError(f"git ls-files --stage failed: {result.stderr.strip()}")
    entries: dict[str, dict[str, str]] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        mode, sha, stage = meta.split(" ")
        if stage != "0":
            raise StagedValidationError(
                f"unresolved (unmerged) index entry, refusing validation: {path}"
            )
        entries[path] = {"mode": mode, "sha": sha}
    return entries


def read_staged_blob(repo_root: Path, sha: str) -> str:
    """R3: read one cached blob by object id -- no checkout, no index mutation."""
    result = _run_git(repo_root, ["cat-file", "-p", sha])
    if result.returncode != 0:
        raise StagedValidationError(f"git cat-file -p {sha} failed: {result.stderr.strip()}")
    return result.stdout


def read_head_blob(repo_root: Path, path: str) -> str | None:
    """R3: HEAD's content of ``path``, or ``None`` if absent from HEAD / no HEAD."""
    if not git_has_head(repo_root):
        return None
    result = _run_git(repo_root, ["show", f"HEAD:{path}"])
    return result.stdout if result.returncode == 0 else None


def _working_baseline(spec_file: Path, revision: str = "HEAD") -> tuple[str | None, bool]:
    result = _run_git(spec_file.parent, ["rev-parse", "--show-toplevel"])
    if result.returncode:
        return None, False
    root = Path(result.stdout.strip())
    relative = spec_file.resolve().relative_to(root.resolve()).as_posix()
    if not git_has_head(root):
        return None, True
    if _run_git(root, ["rev-parse", "--verify", revision + "^{commit}"]).returncode:
        raise StagedValidationError(f"invalid baseline revision: {revision}")
    result = subprocess.run(["git", "-C", str(root), "show", f"{revision}:{relative}"], capture_output=True)
    return (result.stdout.decode("utf-8") if result.returncode == 0 else None), True


def validate_state_rationale_admission(fm: dict, body: str, spec_file: Path) -> list[str]:
    """Strict promotion/runtime gate; private-local records stay in their own root."""
    return list(dict.fromkeys(validate_state_rationale_static(fm, body, spec_file) +
        state_rationale_adoption_findings(fm, body, baseline_available=False, strict=True)))


def rationale_counts(results: dict) -> dict:
    groups = {
        "legacy": ("legacy_missing",),
        "missing": ("required_missing", "adoption_required", "record_required"),
        "stale": ("stale_snapshot", "transition_target_mismatch"),
        "unresolvable_provenance": ("record_not_indexed", "record_wrong_type",
            "record_wrong_owner", "record_unreadable", "record_path_escape", "index_malformed"),
        "unverified_external": ("unverified_external",),
    }
    return {name: sum(any("state_rationale_" + marker in finding for marker in markers)
                     for findings in results.values() for finding in findings)
            for name, markers in groups.items()}


def _snapshot_blobs(repo_root: Path, entries: dict) -> dict[str, bytes]:
    """Read captured object IDs in one binary batch, preserving exact bytes."""
    shas = list(dict.fromkeys(entry["sha"] for entry in entries.values() if entry["mode"] != "160000"))
    result = subprocess.run(["git", "-C", str(repo_root), "cat-file", "--batch"],
                            input=("\n".join(shas) + "\n").encode(), capture_output=True)
    if result.returncode:
        raise StagedValidationError("cannot read captured index blobs")
    blobs = {}
    cursor = 0
    for sha in shas:
        end = result.stdout.index(b"\n", cursor)
        header = result.stdout[cursor:end].split()
        if len(header) != 3 or header[0].decode() != sha or header[1] != b"blob":
            raise StagedValidationError(f"captured object is not a readable blob: {sha}")
        size = int(header[2])
        blobs[sha] = result.stdout[end + 1:end + 1 + size]
        cursor = end + size + 2
    return blobs


def validate_staged(repo_root: Path, specs_relative_dir: str = ".nightshift/specs") -> dict:
    """Validate inert files from one captured index, running only this trusted module.

    The scratch tree is not a checkout: no Git operations write it, no copied
    executable is imported/run, and neither the real index nor worktree changes.
    Symlinks are recreated only when their normalized destination stays inside
    the owning kit; invalid links remain findings rather than filesystem reads.
    """
    repo_root = Path(repo_root).resolve()
    if not lifecycle.is_safe_relative_posix_path(specs_relative_dir):
        raise StagedValidationError("spec root must be a safe repository-relative path")
    entries = staged_index_entries(repo_root)
    has_head = git_has_head(repo_root)
    baseline_revision = _run_git(repo_root, ["rev-parse", "HEAD"]).stdout.strip() if has_head else None
    kit = Path(specs_relative_dir).parent.as_posix()
    prefix = specs_relative_dir.rstrip("/") + "/"
    results = {}
    # R2 (SPEC-380): one `git ls-tree` spawn for every baseline blob sha under
    # the spec prefix, rather than one `git rev-parse` spawn per staged path
    # -- a real corpus is hundreds of files, and a per-path subprocess adds
    # several seconds to every commit that touches specs/ (measured: ~15ms
    # per spawn x 436 real specs).
    baseline_shas: dict[str, str] = {}
    if has_head:
        tree = _run_git(repo_root, ["ls-tree", "-r", "-z", baseline_revision, "--", prefix])
        for record in tree.stdout.split("\0"):
            if not record:
                continue
            meta, tree_path = record.split("\t", 1)
            _mode, _obj_type, sha = meta.split(" ")
            baseline_shas[tree_path] = sha
    blobs = _snapshot_blobs(repo_root, {path: entry for path, entry in entries.items() if path.startswith(kit + "/")})
    with tempfile.TemporaryDirectory(prefix="nightshift-index-") as scratch:
        snapshot = Path(scratch).resolve()
        links = []
        for path, entry in entries.items():
            if not path.startswith(kit + "/"):
                continue
            if not lifecycle.is_safe_relative_posix_path(path):
                raise StagedValidationError(f"unsafe index path: {path!r}")
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["mode"] == "120000":
                links.append((target, blobs[entry["sha"]].decode("utf-8")))
            elif entry["mode"] in {"100644", "100755"}:
                target.write_bytes(blobs[entry["sha"]])
        for target, destination in links:
            resolved = (target.parent / destination).resolve()
            if Path(destination).is_absolute() or not resolved.is_relative_to(snapshot / kit):
                results[target.relative_to(snapshot).as_posix()] = [
                    "state_rationale_evidence_path_escape: staged symlink escapes owning kit"]
            else:
                target.symlink_to(destination)
        config = snapshot / kit / "config.yaml"
        try:
            documents = list(yaml.safe_load_all(config.read_text()))
            if not documents or any(not isinstance(item, dict) for item in documents if item is not None):
                raise ValueError("configuration must contain YAML mappings")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            results[f"{kit}/config.yaml"] = [f"staged_configuration_invalid: {exc}"]
        corpus = _load_directory_frontmatters(snapshot / specs_relative_dir)
        for path in sorted(entries):
            if not path.startswith(prefix) or not path.endswith(".md") or Path(path).name.startswith("_"):
                continue
            # R2 (SPEC-380): determine is_new/bytes_changed from the blob sha
            # up front -- by index sha, not decoded text -- so the gate below
            # applies uniformly to every branch that can populate `results`
            # for this path (symlink-mode, frontmatter-parse-error, and the
            # normal validate_file path), not only the last one.
            baseline_sha = baseline_shas.get(path)
            is_new = baseline_sha is None
            bytes_changed = baseline_sha != entries[path]["sha"]
            reportable = is_new or bytes_changed
            if entries[path]["mode"] == "120000":
                if reportable:
                    results.setdefault(path, []).append("state_rationale_evidence_path_escape: spec must be a regular index file")
                continue
            spec_path = snapshot / path
            text = spec_path.read_bytes().decode("utf-8")
            fm, body, parse_errors, _ = parse_frontmatter_and_body(text)
            if parse_errors:
                if reportable:
                    results[path] = parse_errors
                continue
            findings = validate_file(spec_path, config_path=config, all_specs=corpus, check_adoption=False, git_root=repo_root)
            base_blob = subprocess.run(["git", "-C", str(repo_root), "show", f"{baseline_revision}:{path}"], capture_output=True) if has_head else None
            baseline_text = base_blob.stdout.decode("utf-8") if base_blob is not None and base_blob.returncode == 0 else None
            base_fm, base_body, _, _ = parse_frontmatter_and_body(baseline_text) if baseline_text is not None else (None, None, [], None)
            findings.extend(state_rationale_adoption_findings(
                fm, body, baseline_fm=base_fm, baseline_body=base_body,
                is_new=is_new, bytes_changed=bytes_changed))
            # R2 (SPEC-380): only report findings for a path this commit actually
            # touched (new or changed bytes) — an untouched pre-existing spec's
            # findings never block a commit that didn't change it. The full
            # corpus is still loaded above (R3) so cross-spec context (e.g.
            # duplicate-ID checks) keeps working for the paths that DO report.
            if reportable:
                results[path] = list(dict.fromkeys(finding.replace(str(snapshot), "<index>") for finding in findings))
    return {"baseline": "head" if has_head else "none", "results": results,
            "counts": rationale_counts(results), "finding_families": finding_family_summary(results, [])}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if any(arg == "--staged" for arg in argv):
        rest = [arg for arg in argv if arg != "--staged"]
        repo_root = Path(rest[0]) if rest else Path(".")
        if len(rest) > 1:
            specs_relative_dir = rest[1]
        else:
            # Explicit hook calls use BUG-338's per-path resolver. A standalone
            # invocation without a spec root retains preflight's single-root
            # default and refuses ambiguous roots rather than guessing.
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            try:
                import preflight as _preflight
            except ImportError:
                specs_relative_dir = ".nightshift/specs"  # portable older project kit
            else:
                try:
                    kit_root = _preflight.resolve_kit_root(repo_root)
                except _preflight.KitRootError as exc:
                    # R4: ambiguity/no-root refuses rather than choosing silently.
                    print(f"[validate_specs --staged] REFUSED: {exc}", file=sys.stderr)
                    return 1
                specs_relative_dir = f"{kit_root.relative_to(Path(repo_root).resolve()).as_posix()}/specs"
        try:
            report = validate_staged(repo_root, specs_relative_dir)
        except StagedValidationError as exc:
            print(f"[validate_specs --staged] REFUSED: {exc}", file=sys.stderr)
            return 1
        has_errors = any(
            any(not _is_warning(finding) for finding in findings)
            for findings in report["results"].values()
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if has_errors else 0
    if any(arg in {"--help", "-h"} for arg in argv):
        print(
            "Usage: python3 validate_specs.py <file_or_directory> [...] [--format json|text] "
            "[--promotion-gap-summary] [--ownership-summary] [--baseline PATH] [--base-revision REV]\n"
            "       python3 validate_specs.py --staged <repo-root> [<kit>/specs]\n"
            "       python3 validate_specs.py --check-report-headings <report.md_or_dir> [--format json|text]"
        )
        print("Fleet-wide spec ID collisions are warning-only findings in validation output.")
        return 0
    if not argv:
        print(
            "Usage: python3 validate_specs.py <file_or_directory> [--format json|text] "
            "[--promotion-gap-summary] [--ownership-summary] [--baseline PATH]\n"
            "       python3 validate_specs.py --check-report-headings <report.md_or_dir> [--format json|text]",
            file=sys.stderr,
        )
        return 1

    # SPEC-317 R3: a report file is not a spec file — validate_file() expects
    # spec frontmatter, which reports don't carry. This flag routes to
    # validate_report_headings() instead of the positional spec dispatch
    # below, on request, never implicitly.
    if "--check-report-headings" in argv:
        idx = argv.index("--check-report-headings")
        if idx + 1 >= len(argv):
            print("Error: --check-report-headings requires a path", file=sys.stderr)
            return 1
        fmt_idx = argv.index("--format") if "--format" in argv else -1
        report_fmt = "json" if fmt_idx != -1 and fmt_idx + 1 < len(argv) and argv[fmt_idx + 1] == "json" else "text"
        target = Path(argv[idx + 1])
        if target.is_dir():
            # Top-level only, matching the canonical `YYYY-MM-DD-nightshift-
            # report*.md` filename shape. Does not recurse into subdirectory
            # reports (e.g. `reports/SPEC-248/2026-08-28-nightshift-report.md`).
            report_paths = sorted(target.glob("*-nightshift-report*.md"))
        elif target.is_file():
            report_paths = [target]
        else:
            print(f"Error: {target} does not exist", file=sys.stderr)
            return 1
        report_results = {str(p): validate_report_headings(p) for p in report_paths}
        has_report_errors = any(errors for errors in report_results.values())
        if report_fmt == "json":
            print(json.dumps({"results": report_results}, indent=2, ensure_ascii=False))
        else:
            for path_str, errors in report_results.items():
                status = "OK" if not errors else "FAIL"
                print(f"[{status}] {path_str}")
                for error in errors:
                    print(f"  - {error}")
        return 1 if has_report_errors else 0

    fmt = "text"
    show_promotion_gap_summary = False
    show_ownership_summary = False
    baseline_path: str | None = None
    base_revision = "HEAD"
    status_store_path: Path | None = None  # SPEC-332 R3
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--format" and i + 1 < len(argv):
            fmt = argv[i + 1]
            i += 2
        elif argv[i] == "--promotion-gap-summary":
            show_promotion_gap_summary = True
            i += 1
        elif argv[i] == "--ownership-summary":
            show_ownership_summary = True
            i += 1
        elif argv[i] == "--base-revision" and i + 1 < len(argv):
            base_revision = argv[i + 1]
            i += 2
        elif argv[i] == "--baseline" and i + 1 < len(argv):
            baseline_path = argv[i + 1]
            i += 2
        elif argv[i] == "--status-store" and i + 1 < len(argv):
            status_store_path = Path(argv[i + 1])
            i += 2
        else:
            positional.append(argv[i])
            i += 1

    if not positional:
        print("Error: no path provided", file=sys.stderr)
        return 1

    results: dict[str, list[str]] = {}
    per_path: list[tuple[str, dict[str, list[str]]]] = []
    multiple_paths = len(positional) > 1
    for raw_path in positional:
        path = Path(raw_path)
        if path.is_dir():
            try:
                path_results = validate_directory(path, status_store_path=status_store_path, base_revision=base_revision)
            except (ValueError, StagedValidationError) as exc:
                path_results = {str(path): [str(exc)]}
        elif path.is_file() and path.suffix == ".md":
            try:
                path_results = {path.name: validate_file(path, base_revision=base_revision)}
            except (ValueError, StagedValidationError) as exc:
                path_results = {path.name: [str(exc)]}
            path_results[path.name].extend(
                fleet_uniqueness_findings(path.parent, [path]).get(path.name, [])
            )
        else:
            path_results = {
                str(path): ["path does not exist or is not a Markdown spec file"]
            }

        per_path.append((raw_path, path_results))
        for name, errors in path_results.items():
            key = f"{raw_path}:{name}" if multiple_paths else name
            results[key] = errors

    has_errors = any(
        any(not _is_warning(error) for error in errors)
        for errors in results.values()
    )

    # SPEC-270 R3: --baseline implies computing the current family summary
    # even when --ownership-summary was not separately requested, since a
    # diff needs the "after" side regardless.
    fam_summary = None
    if show_ownership_summary or baseline_path:
        fam_summary = finding_family_summary(
            results, _collect_frontmatters_for_paths(positional)
        )
    fam_diff = None
    baseline_error = None
    if baseline_path:
        try:
            baseline_data = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            baseline_error = f"could not read baseline {baseline_path!r}: {exc}"
        else:
            fam_diff = diff_finding_family_summaries(baseline_data, fam_summary)

    if fmt == "json":
        baseline_labels = set()
        for raw in positional:
            location = Path(raw).parent if Path(raw).is_file() else Path(raw)
            repository = _run_git(location, ["rev-parse", "--show-toplevel"])
            baseline_labels.add("baseline_unavailable" if repository.returncode else
                                base_revision if git_has_head(Path(repository.stdout.strip())) else "none")
        output = {
            "baseline": next(iter(baseline_labels)) if len(baseline_labels) == 1 else "mixed",
            "counts": rationale_counts(results),
            "finding_families": finding_family_summary(results, []),
            "validated_files": len(results),
            "paths_examined": len(positional),
            "files_with_errors": sum(1 for e in results.values() if e),
            "results": results,
        }
        if show_promotion_gap_summary:
            output["promotion_gap_summary"] = promotion_gap_summary(
                _collect_frontmatters_for_paths(positional)
            )
        if show_ownership_summary:
            output["finding_family_summary"] = fam_summary
        if baseline_path:
            output["finding_family_diff"] = fam_diff
            if baseline_error:
                output["finding_family_diff_error"] = baseline_error
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(
            _render_text(
                results,
                positional[0],
                paths_examined=len(positional),
                per_path=per_path,
            )
        )
        if show_promotion_gap_summary:
            summary = promotion_gap_summary(_collect_frontmatters_for_paths(positional))
            print("promotion_gap_summary:")
            for kind, row in summary["by_kind"].items():
                rate = row["rate"] if row["rate"] == "N/A" else f"{row['rate']:.0%}"
                print(f"  {kind}: {row['numerator']}/{row['denominator']} ({rate})")
        if show_ownership_summary:
            print("finding_family_summary:")
            print(
                f"  total={fam_summary['total_findings']} "
                f"owned={fam_summary['owned_findings']} "
                f"unowned={fam_summary['unowned_findings']}"
            )
            for fam in fam_summary["families"]:
                owners = ", ".join(fam["owners"]) if fam["owners"] else "UNOWNED"
                print(f"  - {fam['family']}: count={fam['count']} owners=[{owners}]")
        if baseline_path:
            if baseline_error:
                print(f"finding_family_diff: {baseline_error}")
            else:
                print(f"finding_family_diff: changed={fam_diff['changed']}")
                for change in fam_diff["changes"]:
                    print(f"  - {change['family']}: {change['change']}")

    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
