#!/usr/bin/env python3
"""SPEC-300-001 — shared write/read scope resolver.

Every SPEC-300 enforcement point (harness hook, git guard, evidence gate,
verifier) answers the same question through this module: "is this path
writable/readable for spec S in project P?" Nothing else re-implements the
matching (parent SPEC-300 R2).

Precedence (normative — mirrors SPEC-300 § Defaults/Enforcement)
------------------------------------------------------------------

For ``classify_write``, in order, first match wins:

1. ``malformed_target``  — universal. Evaluated on the raw, unresolved path
   before anything else. A destination whose basename contains ``:`` or a
   newline, or starts/ends with whitespace, is never writable.
2. ``spec_wrong_home``   — universal. A new ``SPEC-*.md`` / ``NFR-*.md`` /
   ``*-QUESTIONS-*.md`` path outside a known specs directory is denied
   regardless of ``write`` and regardless of whether a spec is active,
   UNLESS the path is the active spec's own file (``spec_self`` wins).
3. (scope is ``None``: return ``no_active_spec`` — allowed — here.)
4. ``spec_self``         — the path IS the spec's own file. Wins over deny.
5. ``heartbeat``         — the one sanctioned write outside the worktree
   root: ``.../reports/_wip/orchestrator-progress-<SPEC-ID>.md`` for the
   active spec's own ID.
6. ``denied_glob``       — ``scope.deny`` wins over ``write`` and the
   implicit-allow rules (but not over ``spec_self``).
7. ``implicit_kit_path`` — kit-owned evidence paths are always writable:
   ``reports/**``, ``metrics/**``, ``red-proofs/**``, ``runs/**``,
   ``knowledge/attempts/**``, ``release-handoffs/**``, ``reports/_wip/**``,
   relative to ``kit_dir``. A second, conditional member of this same
   category (SPEC-300-001-001): ``<kit_dir>/CHANGELOG.md`` and
   ``<kit_dir>/release-manifest.json`` are writable, reusing this same
   ``implicit_kit_path`` reason, **only when** the spec's own declared
   ``scope.write`` already names at least one file that is itself a member
   of ``nightshift-sync.py``'s ``CANONICAL_PROTOCOL_FILES`` (i.e. the spec is
   already legitimately editing managed canonical payload). A spec with no
   such relationship gets no exception for either file.
8. ``write_glob`` / ``default_root`` — matches an explicit ``scope.write``
   glob, or (when ``scope.write`` is empty) the project-root default.
9. ``outside_root``      — falls through: outside the project root, or
   inside it but not covered by a non-empty ``scope.write``.

When ``scope`` is ``None`` (no active spec resolvable — SPEC-300 R13),
``classify_write`` evaluates only rules 1 and 2 above and returns
``no_active_spec`` (allowed) for every other path.

``classify_read`` shares the same reason vocabulary and project-root
default; ``deny`` and the implicit-allow rules are write-only (SPEC-300
§ Scope — reads have no ``deny`` and no kit-evidence carve-out).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

# Controlled reason codes (SPEC-300 R2). Every Decision.reason is one of these.
REASONS = frozenset({
    "write_glob",
    "default_root",
    "implicit_kit_path",
    "spec_self",
    "heartbeat",
    "denied_glob",
    "outside_root",
    "spec_wrong_home",
    "malformed_target",
    "no_active_spec",
})

_IMPLICIT_KIT_GLOBS = (
    "reports/**",
    "metrics/**",
    "red-proofs/**",
    "runs/**",
    "knowledge/attempts/**",
    "release-handoffs/**",
    "reports/_wip/**",
)

# SPEC-300-001-001 R1/R2: the *only* two files eligible for the conditional
# canonical-payload exception below. Never widen this tuple.
_CANONICAL_PAYLOAD_EXCEPTION_FILES = frozenset({"CHANGELOG.md", "release-manifest.json"})

_SPEC_HOME_RE = re.compile(r"^(SPEC-.+|NFR-.+|.+-QUESTIONS-.+)\.md$")
_HEARTBEAT_RE = re.compile(r"(?:^|/)reports/_wip/orchestrator-progress-(?P<spec_id>.+)\.md$")
# SPEC-301 R1/R2: this only matches the manually-documented SKILL.md Step 5
# convention (`git worktree add -b nightshift/<SPEC-ID>-<run-id>`), used when
# a platform requires the parent to create the worktree by hand. It is
# deliberately NOT widened to also parse the harness's own
# `isolation: "worktree"` branch shape (observed in this repository as
# `worktree-agent-<hex>`, e.g. `worktree-agent-a3a859e1489cdd8d5`) because
# that hex ID has no derivable relationship to any spec ID — option (a) from
# SPEC-301 R2 is not viable. `NIGHTSHIFT_ACTIVE_SPEC` (checked first, below)
# is the only reliable resolution path for a harness-launched worker; see
# SKILL.md Step 4e for the boilerplate that tells every worker to set it
# inline on every `git commit` invocation.
_BRANCH_RE = re.compile(r"^nightshift/(?P<spec_id>.+)-(?P<run_id>\d{8}T\d+Z?)$")


@dataclass(frozen=True)
class Scope:
    """A spec's resolved ``scope:`` declaration."""

    write: list[str]
    deny: list[str]
    read: str | list[str]


# Absent `scope:` (or a resolved Scope with an empty write list) means the
# whole project root — never "anywhere" (SPEC-300 § Defaults).
DEFAULT_SCOPE = Scope(write=[], deny=[], read="unrestricted")


@dataclass(frozen=True)
class Decision:
    """The verdict for one path."""

    allowed: bool
    reason: str
    path: str

    def __post_init__(self) -> None:
        if self.reason not in REASONS:
            raise ValueError(f"unknown scope_guard reason: {self.reason!r}")


# ---------------------------------------------------------------------------
# Frontmatter / scope resolution
# ---------------------------------------------------------------------------


def resolve_scope(spec_text: str) -> Scope:
    """Parse a spec's ``scope:`` frontmatter block into a :class:`Scope`.

    Pure function of text — this is what lets ``scope_from_main`` compose
    ``git show <main>:<path>`` output directly with no intermediate file.
    Malformed or absent input always resolves to :data:`DEFAULT_SCOPE`
    (project-root default), never to a deny-all — a spec is never
    accidentally unimplementable because its scope failed to parse.
    """
    lines = spec_text.split("\n")
    if not lines or lines[0].strip() != "---":
        return DEFAULT_SCOPE
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return DEFAULT_SCOPE
    fm_text = "\n".join(lines[1:end_idx])
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return DEFAULT_SCOPE
    if not isinstance(fm, dict):
        return DEFAULT_SCOPE
    raw = fm.get("scope")
    if not isinstance(raw, dict):
        return DEFAULT_SCOPE
    write = raw.get("write")
    deny = raw.get("deny")
    read = raw.get("read", "unrestricted")
    write = [str(item) for item in write] if isinstance(write, list) else []
    deny = [str(item) for item in deny] if isinstance(deny, list) else []
    if isinstance(read, list):
        read = [str(item) for item in read]
    elif read != "unrestricted":
        read = "unrestricted"
    return Scope(write=write, deny=deny, read=read)


def scope_from_main(repo: Path, spec_relpath: str, main_branch: str = "main") -> Scope:
    """Read ``scope:`` from ``<spec_relpath>`` as committed on ``main_branch``.

    Never reads the working tree or the worker's branch (SPEC-300 R3) — scope
    widening can only happen through a human-approved commit on main. Falls
    closed to the project-root default (not a deny-all) when the spec does
    not exist on main: a brand-new spec on a worker branch has no scope
    history to trust, so the widest permissible default applies and the
    spec-creation itself is judged by the spec-home rule, not this function.

    SPEC-302 R1/R3: the value read above is only *provisional* — before
    returning it, ``_reconcile_scope_widening`` checks it against the value
    that was in effect the last time this spec was ``ready`` on main. A
    widening with no covering ``## Scope Amendments`` row is rolled back
    (per field) to that prior value. This is the single reconciliation point
    both the evidence-gate embedded script (which calls this function
    directly) and the git guard (whose ``scope_guard.py check`` CLI also
    calls this function) share — see module docstring precedence note 6/8.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{main_branch}:{spec_relpath}"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except OSError:
        return DEFAULT_SCOPE
    if result.returncode != 0:
        return DEFAULT_SCOPE
    current = resolve_scope(result.stdout)
    return _reconcile_scope_widening(repo, spec_relpath, main_branch, current, result.stdout)


# ---------------------------------------------------------------------------
# SPEC-302 — mechanical scope-amendment gate
# ---------------------------------------------------------------------------

_SCOPE_AMENDMENTS_HEADING_RE = re.compile(
    r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", re.MULTILINE
)
_SCOPE_AMENDMENTS_SEPARATOR_RE = re.compile(r"^\|[\s:|-]*\|?$")
_AMENDMENT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HUMAN_APPROVAL_RE = re.compile(r"^human(:.+)?$")


def _spec_status_from_text(spec_text: str) -> str | None:
    """Best-effort ``status:`` frontmatter value, or ``None`` if absent/malformed."""
    lines = spec_text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip().strip("'\"") or None
    return None


def _scope_at_last_ready(
    repo: Path, spec_relpath: str, main_branch: str
) -> tuple[Scope, str] | None:
    """The ``Scope`` and commit hash of the most recent commit on ``main_branch``
    at which this spec's ``status:`` *transitioned into* ``ready``.

    SPEC-302-001 R1: walking history newest-first, a commit only qualifies
    when its own ``status:`` reads ``ready`` **and** the immediately
    preceding commit for this spec file (older, in ``--follow`` history) had
    a different ``status:`` — or no prior commit exists at all. A commit
    that merely *reads* ``ready`` because its predecessor was already
    ``ready`` is not a transition and is skipped; older history is searched
    for the actual last transition-into-``ready`` commit. This closes the
    widen-while-still-``ready`` bypass: a widening commit landed while
    ``status:`` stays ``ready`` (never passing through ``in_progress``) can
    no longer become its own reconciliation baseline.

    Returns ``None`` when no such commit exists — a spec that has never
    transitioned into ``ready`` on main has no widening to reconcile against
    (R5): the current value is used as-is, unconditionally.
    """
    try:
        log = subprocess.run(
            ["git", "log", "--format=%H", "--follow", main_branch, "--", spec_relpath],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if log.returncode != 0:
        return None
    commits = log.stdout.split()
    # Third element distinguishes "genuinely no prior commit" (``end``, past
    # the end of history) from "a commit exists here but couldn't be read for
    # this path" (``unreadable`` — e.g. a `git show` failure this function
    # cannot otherwise explain, most plausibly a rename this pathspec-fixed
    # walk cannot follow). These are NOT the same thing for R1's transition
    # test: only the former licenses treating a `ready` commit as a fresh
    # transition. When a candidate's predecessor is unreadable, that specific
    # candidate is skipped rather than accepted as a transition (its
    # predecessor's status is unknown and must never be assumed to differ
    # from `ready`). This does not by itself guarantee no bypass: if every
    # remaining candidate is exhausted this way, the function returns
    # ``None`` and the caller (`_reconcile_scope_widening`) uses the current
    # value unconditionally — the same safe-default behavior R5 already
    # specifies for "never been ready", per this spec's stop-immediately
    # rule against falling closed to DENY. A residual, not a regression: the
    # pre-fix function had no transition test at all.
    cache: dict[int, tuple[str | None, str | None, str]] = {}

    def fetch(idx: int) -> tuple[str | None, str | None, str]:
        if idx not in cache:
            if idx >= len(commits):
                cache[idx] = (None, None, "end")
            else:
                try:
                    show = subprocess.run(
                        ["git", "show", f"{commits[idx]}:{spec_relpath}"],
                        cwd=repo,
                        capture_output=True,
                        text=True,
                    )
                except OSError:
                    cache[idx] = (None, None, "unreadable")
                else:
                    if show.returncode != 0:
                        cache[idx] = (None, None, "unreadable")
                    else:
                        cache[idx] = (show.stdout, _spec_status_from_text(show.stdout), "ok")
        return cache[idx]

    for i in range(len(commits)):
        text, status, kind = fetch(i)
        if kind != "ok" or status != "ready":
            continue
        _, preceding_status, preceding_kind = fetch(i + 1)
        if preceding_kind == "unreadable":
            # Cannot prove the predecessor differed from `ready` — never
            # treat this as a transition; keep searching older history.
            continue
        if preceding_kind != "end" and preceding_status == "ready":
            continue
        return resolve_scope(text), commits[i]
    return None


def _commit_date(repo: Path, commit: str) -> str | None:
    """``YYYY-MM-DD`` (author date) for ``commit``, or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%aI", commit],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    stamp = result.stdout.strip()
    return stamp[:10] if len(stamp) >= 10 else None


def _valid_amendment_rows(spec_text: str) -> list[tuple[str, str]]:
    """``(date, glob)`` pairs from every ``## Scope Amendments`` row with a
    parseable ``Date`` and a human ``Approved by`` (mirrors
    ``validate_specs.py``'s row-shape rules — same heading regex, same
    skip-header/separator/short-row logic — but this is R1's widening-gate
    read of the table, a different consumer than the pre-existing per-path
    ``amend_globs`` read in the embedded SKILL.md gate script).
    """
    match = _SCOPE_AMENDMENTS_HEADING_RE.search(spec_text)
    if not match:
        return []
    rows: list[tuple[str, str]] = []
    for line in match.group(1).split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|") or _SCOPE_AMENDMENTS_SEPARATOR_RE.match(stripped):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not any(cells) or cells[0] == "Date" or len(cells) < 5:
            continue
        date, glob, approved_by = cells[0], cells[1], cells[4]
        if not glob or not approved_by or not date:
            continue
        if not _AMENDMENT_DATE_RE.match(date):
            continue
        if not _HUMAN_APPROVAL_RE.match(approved_by):
            continue
        rows.append((date, glob))
    return rows


def _covered_by_amendment(item: str, rows: list[tuple[str, str]], min_date: str | None) -> bool:
    """Is ``item`` (a literal glob string this widening newly grants) covered
    by some valid amendment row dated on or after ``min_date``?

    Coverage is string-level via the same ``_glob_match`` used for path
    classification (an amendment row's glob pattern matching the granted
    item), not semantic glob subsumption — a row of ``src/**`` covers a
    grant of ``src/auth/**``, but two independently-phrased globs that
    happen to describe overlapping paths are not recognized as equivalent.
    """
    for date, glob in rows:
        if min_date is not None and date < min_date:
            continue
        if glob == item or _glob_match(glob, item):
            return True
    return False


def _reconcile_scope_widening(
    repo: Path,
    spec_relpath: str,
    main_branch: str,
    current: Scope,
    spec_text_main: str,
) -> Scope:
    """R1/R2/R3: fall back any *uncovered* widening (per field) to the value in
    effect when the spec was last ``ready`` on main; never touch a narrowing.

    A field only ever falls back to its last-ready value when that field
    specifically grew wider with no covering ``## Scope Amendments`` row —
    each of ``write``/``deny``/``read`` is judged independently, so an
    approved widening in one field never masks (or is masked by) an
    unrelated narrowing in another (R2).

    SPEC-302-001 R2: within a single field, reconciliation is never a
    per-field baseline-or-current binary choice. A commit that both narrows
    (drops an existing item) and widens (adds an uncovered item) the *same*
    field only reverts the specific uncovered addition — the dropped item
    stays dropped, because the human never asked to keep it.
    """
    baseline_info = _scope_at_last_ready(repo, spec_relpath, main_branch)
    if baseline_info is None:
        return current
    baseline, ready_commit = baseline_info
    if baseline == current:
        return current
    min_date = _commit_date(repo, ready_commit)
    rows = _valid_amendment_rows(spec_text_main)

    # write: baseline.write == [] is already the project-root default (the
    # widest possible value) — nothing can widen it further, so any current
    # value is a narrowing and always takes effect (R2).
    if baseline.write:
        if not current.write:
            # Collapsed to the project-root default — the maximal possible
            # widening with no per-item list to partially narrow. Binary by
            # construction: either the collapse itself is covered, or the
            # whole field reverts to baseline.
            write = current.write if _covered_by_amendment("**", rows, min_date) else baseline.write
        else:
            grants = [g for g in current.write if g not in baseline.write]
            uncovered = [g for g in grants if not _covered_by_amendment(g, rows, min_date)]
            # Drop only the uncovered new grants; anything the commit already
            # narrowed out of `current.write` stays dropped (R2) — never
            # restored as a side effect of blocking the uncovered addition.
            write = [g for g in current.write if g not in uncovered]
    else:
        write = current.write

    # deny: removing an entry widens (it uncovers whatever that entry denied);
    # adding an entry narrows and always takes effect immediately. Restore
    # only the specific uncovered removals — an entry the commit newly added
    # to `deny` in the same commit is never discarded as a side effect.
    removed = [g for g in baseline.deny if g not in current.deny]
    uncovered_removed = [g for g in removed if not _covered_by_amendment(g, rows, min_date)]
    deny = current.deny + [g for g in uncovered_removed if g not in current.deny]

    # read: baseline.read == "unrestricted" is already maximal; a list
    # baseline can widen either to "unrestricted" or by gaining new entries.
    if isinstance(baseline.read, list):
        if current.read == "unrestricted":
            # Collapsed to unrestricted — binary for the same reason as the
            # write collapse above: there is no per-item list to narrow.
            read = current.read if _covered_by_amendment("**", rows, min_date) else baseline.read
        elif isinstance(current.read, list):
            grants = [g for g in current.read if g not in baseline.read]
            uncovered = [g for g in grants if not _covered_by_amendment(g, rows, min_date)]
            read = [g for g in current.read if g not in uncovered]
        else:
            read = current.read
    else:
        read = current.read

    return Scope(write=write, deny=deny, read=read)


def active_spec(env: dict | None, branch_name: str | None) -> str | None:
    """Resolve the active spec ID from env or the worker branch name.

    ``NIGHTSHIFT_ACTIVE_SPEC`` always wins when set (SPEC-300 § Enforcement).
    Otherwise a ``nightshift/<SPEC-ID>-<run-id>`` branch name is parsed.
    Returns ``None`` on ``main`` (or any non-matching branch) with no env
    var — interactive multi-repository sessions are unaffected.

    SPEC-301: a harness-assigned `isolation: "worktree"` branch (observed
    shape: ``worktree-agent-<hex>``) never matches ``_BRANCH_RE`` and
    correctly falls through to ``None`` here — the hex ID carries no spec
    identity, so branch-name parsing cannot resolve it. This is the expected,
    safe behavior (R5): with no env var set, such a worker classifies as
    ``no_active_spec`` (allow) rather than a false deny. Real resolution for
    that shape depends entirely on ``NIGHTSHIFT_ACTIVE_SPEC`` being set.
    """
    value = (env or {}).get("NIGHTSHIFT_ACTIVE_SPEC")
    if value:
        return str(value)
    if not branch_name:
        return None
    match = _BRANCH_RE.match(branch_name)
    if not match:
        return None
    return match.group("spec_id")


# ---------------------------------------------------------------------------
# Glob matching — gitignore-style, ** crosses directories.
# ---------------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> re.Pattern:
    pattern = pattern.replace("\\", "/").lstrip("/")
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i : i + 3] == "**/":
            out.append(r"(?:.*/)?")
            i += 3
            continue
        if pattern[i : i + 2] == "**":
            out.append(r".*")
            i += 2
            continue
        c = pattern[i]
        if c == "*":
            out.append(r"[^/]*")
        elif c == "?":
            out.append(r"[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    body = "".join(out)
    # A wildcard-free directory pattern ("src/search") also matches its
    # contents, gitignore-style.
    return re.compile(rf"^{body}(?:/.*)?$")


def _glob_match(pattern: str, path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return bool(_glob_to_regex(pattern).match(normalized))


def _any_match(patterns: Iterable[str], path: str) -> bool:
    return any(_glob_match(pattern, path) for pattern in patterns)


# ---------------------------------------------------------------------------
# Malformed-target / spec-home universal rules
# ---------------------------------------------------------------------------


def _basename(path_str: str) -> str:
    normalized = path_str.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def _is_malformed(path_str: str) -> bool:
    basename = _basename(path_str)
    if not basename:
        return False
    if ":" in basename or "\n" in basename:
        return True
    if basename != basename.strip():
        return True
    return False


def _norm(path_str: str) -> str:
    """Normalize separators only — never resolve/collapse ``..`` here.

    ``outside_root`` must still see the raw ``../x`` shape; normalization is
    limited to backslash conversion so string comparisons are stable.
    """
    return path_str.replace("\\", "/")


def _discover_specs_dirs(project_root: Path) -> tuple[set[str], str | None]:
    """Fleet discovery, reusing ``doctor.py``'s ``find_projects`` (R12).

    Returns project-root-relative specs-directory strings. An empty result
    (with an explanatory warning) means discovery found nothing usable — the
    spec-home rule then falls open rather than producing a false denial.
    """
    here = Path(__file__).resolve().parent
    doctor_file = here.parent / "doctor.py"
    dirs: set[str] = set()
    try:
        if doctor_file.is_file():
            spec = importlib.util.spec_from_file_location("_scope_guard_doctor", doctor_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for project in module.find_projects([project_root]):
                    candidate = project / ".nightshift" / "specs"
                    if candidate.is_dir():
                        try:
                            dirs.add(_norm(str(candidate.relative_to(project_root))))
                        except ValueError:
                            pass
    except Exception:
        # Dynamic-import-based fleet discovery must never raise, but if it
        # does (e.g. a doctor.py/interpreter interaction), the always-safe
        # hardcoded fallback below must still run rather than the rule
        # falling open here (BUG-020). Only fall open if that fallback also
        # finds nothing usable.
        pass
    for fallback in (project_root / ".nightshift" / "specs", project_root / "canonical" / "specs"):
        if fallback.is_dir():
            dirs.add(_norm(str(fallback.relative_to(project_root))))
    if dirs:
        return dirs, None
    return set(), "scope_guard: no specs directory discovered; spec-home rule falls open"


def _known_specs_dirs(project_root: Path, known_specs_dirs: set[Path] | None) -> tuple[set[str], str | None]:
    # `None` (the default) means "discover for me". An explicitly empty set
    # means "discovery already ran and found nothing" — both fall open, but
    # only the unset case re-attempts discovery (R12).
    if known_specs_dirs is None:
        return _discover_specs_dirs(project_root)
    if not known_specs_dirs:
        return set(), "scope_guard: specs-directory discovery failed; spec-home rule falls open"
    rels: set[str] = set()
    for entry in known_specs_dirs:
        entry_path = Path(entry)
        try:
            rels.add(_norm(str(entry_path.resolve().relative_to(project_root.resolve()))))
        except ValueError:
            rels.add(_norm(str(entry)))
    return rels, None


def _managed_payload_names(kit_dir: Path) -> frozenset[str]:
    """Return the kit-relative paths the release manifest declares as payload.

    BUG-321: the spec-home rule matches on basename, and ``SPEC-GUIDE.md`` — the
    kit's authoring guide, a ``CANONICAL_PROTOCOL_FILES`` member that correctly
    lives at the kit root — matches it. Denying it makes every guarded release
    uncommittable in any repository whose ``pre-commit`` runs this guard, because
    ``release_coordinator.py`` stages exactly the manifest's payload.

    Membership is read from the kit itself, so a future managed file with a
    spec-shaped name needs no further patch:

    * ``release-marker.json`` embeds the complete per-file manifest and is
      written into every install (``release.apply_install``), so this works
      away from canonical;
    * ``release-manifest.json`` is the canonical checkout's own copy and is not
      itself delivered as payload.

    Fail-closed: anything missing, unreadable or malformed yields an empty set,
    which means "not managed payload" and leaves the violation firing (R3).
    """
    for name, extract in (
        ("release-marker.json", lambda d: d.get("release_manifest", {}).get("files", [])),
        ("release-manifest.json", lambda d: d.get("files", [])),
    ):
        source = kit_dir / name
        if not source.is_file():
            continue
        try:
            entries = extract(json.loads(source.read_text()))
            names = {
                _norm(str(entry["path"]))
                for entry in entries
                if isinstance(entry, dict) and entry.get("path")
            }
        except Exception:  # pragma: no cover - malformed kit metadata never raises
            continue
        if names:
            return frozenset(names)
    return frozenset()


_KIT_METADATA_NAMES = ("release-marker.json", "release-manifest.json")


def _candidate_kit_dirs(
    path_str: str, project_root: Path, kit_dir: Path | None
) -> list[Path]:
    """BUG-335: the kit directories a staged path might belong to, nearest first.

    A repository can hold more than one kit: the canonical source and any number
    of installs, including one nested inside the canonical source. The kit a path
    belongs to is the nearest ancestor carrying kit metadata -- exactly the files
    ``_managed_payload_names`` already reads, so this adds no second convention.
    ``release.apply_install`` writes ``release-marker.json`` into every install,
    so each install root is self-identifying without reaching back to canonical.

    The caller-supplied ``kit_dir`` is appended last as a fallback, preserving
    single-kit behaviour for paths with no metadata-bearing ancestor (R4).
    """
    candidates: list[Path] = []
    normalized = _norm(path_str)
    base = Path(normalized) if os.path.isabs(normalized) else (project_root / normalized)
    try:
        resolved = base.resolve()
        root = project_root.resolve()
    except OSError:
        resolved = None
        root = project_root
    if resolved is not None:
        for ancestor in resolved.parents:
            if any((ancestor / name).is_file() for name in _KIT_METADATA_NAMES):
                candidates.append(ancestor)
            if ancestor == root:
                break
    if kit_dir is not None and not any(
        _same_path(kit_dir, existing) for existing in candidates
    ):
        candidates.append(kit_dir)
    return candidates


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _is_spec_home_violation(
    path_str: str,
    project_root: Path,
    known_specs_dirs: set[Path] | None,
    kit_dir: Path | None = None,
) -> tuple[bool, str | None]:
    """Return ``(violation, warning)`` for the universal spec-home rule."""
    basename = _basename(path_str)
    if not _SPEC_HOME_RE.match(basename):
        return False, None
    # BUG-321: the kit's own manifest-declared payload is never a misplaced
    # spec, wherever inside the kit it sits. Keyed on manifest membership, so
    # a spec-shaped path that is NOT payload is still denied (R2).
    #
    # BUG-335: resolve the kit per path, not once per invocation. A repository
    # may hold several kit directories -- the Nightshift repo holds `canonical/`
    # plus installs at `.nightshift/` and `canonical/.nightshift/` -- and
    # `release_coordinator.py` stages payload for all of them in one commit. A
    # single caller-supplied `kit_dir` recognises at most one of them, so the
    # rest were denied and a multi-install repository could not be released.
    # The caller's `kit_dir` remains the fallback (R4).
    for candidate in _candidate_kit_dirs(path_str, project_root, kit_dir):
        kit_rel = _kit_relative(path_str, project_root, candidate)
        if kit_rel is not None and kit_rel in _managed_payload_names(candidate):
            return False, None
    specs_dirs, warning = _known_specs_dirs(project_root, known_specs_dirs)
    if not specs_dirs:
        return False, warning
    parts = _norm(path_str).rsplit("/", 1)
    parent_dir = parts[0] if len(parts) == 2 else ""
    return parent_dir not in specs_dirs, None


# ---------------------------------------------------------------------------
# classify_write / classify_read
# ---------------------------------------------------------------------------


def classify_write(
    path: str,
    scope: Scope | None,
    project_root: Path,
    kit_dir: Path,
    spec_path: str | None,
    *,
    known_specs_dirs: set[Path] | None = None,
) -> Decision:
    """Classify ``path`` (project-root-relative or absolute) for a write."""
    path_str = str(path)

    if _is_malformed(path_str):
        return Decision(False, "malformed_target", path_str)

    is_spec_self = (
        scope is not None
        and spec_path is not None
        and _norm(path_str) == _norm(str(spec_path))
    )

    violation, warning = _is_spec_home_violation(
        path_str, project_root, known_specs_dirs, kit_dir
    )
    if warning:
        print(warning, file=sys.stderr)
    if violation and not is_spec_self:
        return Decision(False, "spec_wrong_home", path_str)

    if scope is None:
        return Decision(True, "no_active_spec", path_str)

    if is_spec_self:
        return Decision(True, "spec_self", path_str)

    heartbeat_match = _HEARTBEAT_RE.search(_norm(path_str))
    if heartbeat_match and spec_path is not None:
        spec_id = _spec_id_from_path(spec_path, project_root)
        if spec_id and heartbeat_match.group("spec_id") == spec_id:
            return Decision(True, "heartbeat", path_str)

    project_relative = _project_relative(path_str, project_root)

    if project_relative is not None and _any_match(scope.deny, project_relative):
        return Decision(False, "denied_glob", path_str)

    kit_relative = _kit_relative(path_str, project_root, kit_dir)
    if kit_relative is not None and _any_match(_IMPLICIT_KIT_GLOBS, kit_relative):
        return Decision(True, "implicit_kit_path", path_str)

    # SPEC-300-001-001 R1/R2: conditional exception for exactly these two
    # files, gated on the spec's own declared `scope.write` already touching
    # managed canonical payload. No relationship -> no exception (R5).
    if (
        kit_relative is not None
        and kit_relative in _CANONICAL_PAYLOAD_EXCEPTION_FILES
        and _touches_managed_canonical_payload(scope, project_root, kit_dir)
    ):
        return Decision(True, "implicit_kit_path", path_str)

    if project_relative is None:
        return Decision(False, "outside_root", path_str)

    if not scope.write:
        return Decision(True, "default_root", path_str)

    if _any_match(scope.write, project_relative):
        return Decision(True, "write_glob", path_str)

    return Decision(False, "outside_root", path_str)


def classify_read(path: str, scope: Scope | None, project_root: Path) -> Decision:
    """Classify ``path`` for a read. Reads have no ``deny`` or kit carve-out."""
    path_str = str(path)
    if scope is None:
        return Decision(True, "no_active_spec", path_str)
    if scope.read == "unrestricted":
        return Decision(True, "default_root", path_str)
    project_relative = _project_relative(path_str, project_root)
    if project_relative is None:
        return Decision(False, "outside_root", path_str)
    if isinstance(scope.read, list) and _any_match(scope.read, project_relative):
        return Decision(True, "write_glob", path_str)
    return Decision(False, "outside_root", path_str)


def _spec_id_from_path(spec_path: str, project_root: Path | None = None) -> str | None:
    """Best-effort spec ID for the heartbeat rule.

    Prefers the authoritative ``id:`` frontmatter field (filenames carry a
    free-text title suffix, e.g. ``SPEC-1-demo.md``, that a filename-only
    regex cannot distinguish from a multi-segment numeric ID such as
    ``SPEC-300-001``). Falls back to a numeric-suffix heuristic on the
    filename when the file cannot be read.
    """
    if project_root is not None:
        candidate = project_root / str(spec_path)
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            text = None
        if text is not None:
            lines = text.split("\n")
            if lines and lines[0].strip() == "---":
                for line in lines[1:]:
                    if line.strip() == "---":
                        break
                    if line.startswith("id:"):
                        return line.split(":", 1)[1].strip().strip("'\"") or None
    basename = _basename(str(spec_path))
    stem = basename[:-3] if basename.endswith(".md") else basename
    match = re.match(r"^((?:SPEC|NFR|BUG|EVAL|FART)-\d+(?:-\d+)*)", stem)
    return match.group(1) if match else None


def _project_relative(path_str: str, project_root: Path) -> str | None:
    """Project-root-relative posix path, or ``None`` if outside the root."""
    normalized = _norm(path_str)
    if os.path.isabs(normalized):
        try:
            resolved = Path(normalized).resolve()
            rel = resolved.relative_to(project_root.resolve())
        except (ValueError, OSError):
            return None
        return _norm(str(rel))
    try:
        resolved = (project_root / normalized).resolve()
        rel = resolved.relative_to(project_root.resolve())
    except (ValueError, OSError):
        return None
    return _norm(str(rel))


def _kit_relative(path_str: str, project_root: Path, kit_dir: Path) -> str | None:
    normalized = _norm(path_str)
    base = Path(normalized) if os.path.isabs(normalized) else (project_root / normalized)
    try:
        resolved = base.resolve()
        rel = resolved.relative_to(kit_dir.resolve())
    except (ValueError, OSError):
        return None
    return _norm(str(rel))


def _canonical_protocol_files(kit_dir: Path) -> frozenset[str] | None:
    """Load ``nightshift-sync.py``'s ``CANONICAL_PROTOCOL_FILES`` for the R1
    membership test, without importing it as a package module (it is itself
    tracked by the very same release manifest — SPEC-300-001-001 mirrors the
    load pattern already used by ``validate_install.py``'s ``_canonical_names``).

    Returns ``None`` when ``nightshift-sync.py`` cannot be located or loaded.
    This is a fail-closed helper: the conditional canonical-payload exception
    simply never fires in that case (R5) — it never fails open to a blanket
    allow.
    """
    sync_path = kit_dir.parent / "nightshift-sync.py"
    if not sync_path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_scope_guard_nightshift_sync", sync_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return frozenset(str(f) for f in module.CANONICAL_PROTOCOL_FILES)
    except Exception:  # pragma: no cover - loader failure must never raise
        return None


def _touches_managed_canonical_payload(scope: Scope, project_root: Path, kit_dir: Path) -> bool:
    """R1 gate: does ``scope.write`` already name a file that is itself a
    member of the release manifest's managed set?

    This is the sole condition for the ``CHANGELOG.md``/``release-manifest.json``
    exception (R1, R5) — a spec whose ``scope.write`` has no overlap with
    ``CANONICAL_PROTOCOL_FILES`` gets no exception for either file.
    """
    protocol_files = _canonical_protocol_files(kit_dir)
    if not protocol_files:
        return False
    for declared in scope.write:
        kit_rel = _kit_relative(declared, project_root, kit_dir)
        if kit_rel is not None and kit_rel in protocol_files:
            return True
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _locate_spec_file(project_root: Path, spec: str) -> Path | None:
    if "/" in spec or spec.endswith(".md"):
        candidate = project_root / spec
        return candidate if candidate.is_file() else None
    for specs_dir in (project_root / "canonical" / "specs", project_root / "specs", project_root / ".nightshift" / "specs"):
        if not specs_dir.is_dir():
            continue
        matches = sorted(specs_dir.glob(f"{spec}-*.md")) + sorted(specs_dir.glob(f"{spec}.md"))
        if matches:
            return matches[0]
    return None


def _cli_check(args: argparse.Namespace) -> int:
    project_root = Path(args.root).resolve()
    spec_file = _locate_spec_file(project_root, args.spec)
    if spec_file is not None:
        spec_relpath = _norm(str(spec_file.relative_to(project_root)))
        kit_dir = spec_file.parent.parent
        scope = scope_from_main(project_root, spec_relpath, args.main)
    else:
        spec_relpath = args.spec
        kit_dir = project_root / "canonical" if (project_root / "canonical").is_dir() else project_root / ".nightshift"
        scope = None

    if args.paths_from_stdin:
        paths = [line.strip() for line in sys.stdin if line.strip()]
    else:
        paths = list(args.paths)

    decisions = [
        classify_write(path, scope, project_root, kit_dir, spec_relpath)
        for path in paths
    ]

    if args.json:
        print(json.dumps([
            {"allowed": d.allowed, "reason": d.reason, "path": d.path} for d in decisions
        ], indent=2))
    else:
        for d in decisions:
            print(f"{'ALLOW' if d.allowed else 'DENY'} {d.reason} {d.path}")

    return 0 if all(d.allowed for d in decisions) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scope_guard.py")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Classify paths against a spec's declared write scope.")
    check.add_argument("--spec", required=True, help="Spec ID or path (project-root-relative).")
    check.add_argument("--root", required=True, help="Project root (git toplevel).")
    check.add_argument("--main", default="main", help="Main branch to read scope: from (default: main).")
    check.add_argument("--json", action="store_true", help="Emit JSON instead of text lines.")
    check.add_argument("--paths-from-stdin", action="store_true", help="Read newline-separated paths from stdin.")
    check.add_argument("paths", nargs="*", help="Paths to classify.")
    check.set_defaults(func=_cli_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
