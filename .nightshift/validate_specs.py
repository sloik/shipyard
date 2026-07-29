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
import sys
from pathlib import Path

from lifecycle import migrate_legacy_planning, validate_blocked

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

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

    Uses yaml.safe_load so both quoted (``"2.24.0"``) and unquoted
    (``2.24.0``) values parse correctly.  All exceptions are silently caught
    so a missing or malformed config always produces the safe default (R3).
    """
    if config_path is None or not config_path.is_file():
        return None
    try:
        raw = config_path.read_text(encoding="utf-8")
        cfg = yaml.safe_load(raw) or {}
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


def validate_file(spec_file: Path, config_path: Path | None = None, all_specs: list[dict] | None = None) -> list:
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
        content = spec_file.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read file: {exc}"]

    # Parse frontmatter manually so this validator works even when
    # spec_frontmatter is not importable (project .nightshift/ copies).
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return ["missing opening frontmatter delimiter ('---')"]

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return ["missing closing frontmatter delimiter ('---')"]

    fm_text = "\n".join(lines[1:end_idx])
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        return [f"invalid YAML frontmatter: {exc}"]

    if not isinstance(fm, dict):
        return ["frontmatter must be a YAML mapping"]

    body = "\n".join(lines[end_idx + 1:])
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
    errors.extend(validate_reuse_gate(body))

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
        for line_number, line in enumerate(lines[end_idx + 1:], start=end_idx + 2):
            if line.startswith("## "):
                _current_section = _checked_sections.get(line.strip())
            elif _current_section and re.match(r"^\s*- \[ \]", line):
                errors.append(
                    f"{spec_file}:{line_number}: status is 'done' but has an unchecked "
                    f"checkbox in {_current_section}: {line.strip()}"
                )

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
        cfg = yaml.safe_load(raw) or {}
    except Exception as exc:
        findings.append(f"WARNING: could not read config.yaml: {exc}")
        return findings

    if not isinstance(cfg, dict):
        return findings  # not a mapping — other validators handle this

    override = cfg.get("board_column_defaults")
    if override is None:
        return findings  # absent section — nothing to check

    problems = _check_column_override(override)
    for problem in problems:
        findings.append(f"WARNING: board_column_defaults: {problem}")

    return findings


def validate_directory(specs_dir: Path) -> dict:
    """Validate all .md files in specs_dir. Returns {filename: [errors]}."""
    if not specs_dir.is_dir():
        raise ValueError(f"not a directory: {specs_dir}")

    results = {}
    all_specs = _load_directory_frontmatters(specs_dir)
    for spec_file in sorted(specs_dir.glob("*.md")):
        if spec_file.name.startswith("_"):
            continue  # skip template files
        results[spec_file.name] = validate_file(spec_file, all_specs=all_specs)

    # SPEC-071 R9a: validate the sibling projects-registry.json when present
    # (specs_dir is typically `.nightshift/specs`; the registry is its sibling).
    registry = specs_dir.parent / "projects-registry.json"
    if registry.is_file():
        results[registry.name] = validate_registry_file(registry)

    # SPEC-080: validate the sibling config.yaml board_column_defaults when present.
    config_yaml = specs_dir.parent / "config.yaml"
    if config_yaml.is_file():
        results[config_yaml.name] = validate_config_file(config_yaml)

    return results


def _is_warning(msg: str) -> bool:
    return msg.startswith("WARNING: ")


def _render_text(results: dict, source: str) -> str:
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
        lines.append(f"[nightshift validate-specs] OK — {file_count} spec(s) valid")
        return "\n".join(lines)

    if error_count == 0:
        lines.append(
            f"[nightshift validate-specs] OK (with {warning_count} warning(s)) "
            f"— {file_count} spec(s) checked"
        )
    else:
        lines.append(
            f"[nightshift validate-specs] FAILED — {bad_count}/{file_count} spec(s) have errors"
        )
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


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        print(
            "Usage: python3 validate_specs.py <file_or_directory> [--format json|text]",
            file=sys.stderr,
        )
        sys.exit(1)

    fmt = "text"
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--format" and i + 1 < len(argv):
            fmt = argv[i + 1]
            i += 2
        else:
            positional.append(argv[i])
            i += 1

    if not positional:
        print("Error: no path provided", file=sys.stderr)
        sys.exit(1)

    path = Path(positional[0])

    if path.is_dir():
        try:
            results = validate_directory(path)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            sys.exit(1)
        has_errors = any(
            any(not _is_warning(e) for e in errs) for errs in results.values()
        )
    elif path.is_file():
        errors = validate_file(path)
        results = {path.name: errors}
        has_errors = any(not _is_warning(e) for e in errors)
    else:
        # Multiple files passed as positional args (e.g. from git diff | xargs)
        results = {}
        for p in positional:
            fp = Path(p)
            if fp.is_file() and fp.suffix == ".md":
                results[fp.name] = validate_file(fp)
        has_errors = any(
            any(not _is_warning(e) for e in errs) for errs in results.values()
        )

    if fmt == "json":
        output = {
            "validated_files": len(results),
            "files_with_errors": sum(1 for e in results.values() if e),
            "results": results,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        source = str(path)
        print(_render_text(results, source))

    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
