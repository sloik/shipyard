#!/usr/bin/env python3
"""config_migrations.py — registered, deterministic config schema migrations (SPEC-269).

`Skills/nightshift/SKILL.md` Step 3 ("Plan configuration migrations") requires every
per-install migration worker the release coordinator dispatches to follow "the
registered deterministic migration" for the schema bump it is carrying out. This
module IS that registry: one pure, idempotent, text-in/text-out function per target
`schema_version`, keyed by the version it migrates an install *to*.

Design constraints (SPEC-269 R3 / AC2):
  - **Pure.** No filesystem, network, or other side effects — callers read/write
    ``config.yaml`` themselves (see ``release_coordinator.default_migration_runner``
    for a reference caller).
  - **Idempotent.** ``migrate(migrate(text)) == migrate(text)``.
  - **Untouched at/above target.** A config already at or above the target
    ``schema_version`` is returned byte-identical.
  - **Additive only.** Adds a block only when the corresponding top-level key is
    absent; never rewrites an install's existing customization of a block that's
    already present.

``config.yaml`` is a multi-document YAML stream (``---``-separated); top-level keys
are matched with a line-anchored regex exactly like ``release.kit_version()`` and
``release_coordinator._schema_version()`` do, rather than a full YAML round-trip,
so this migration never reformats or reorders unrelated documents or comments.
"""

from __future__ import annotations

import re

# SPEC-327 R4: shared table. validate_install.py's REQUIRED_CONFIG_SECTIONS
# and the CFG.RUNNER_POLICY invariant's section tuple live HERE, not in
# validate_install.py, and validate_install.py imports them from this module
# (see its `import config_migrations` and the assignments right after it).
# This module has no reason to import validate_install (which pulls in
# PyYAML, release.py, and managed_payload_provenance, and would break this
# module's stated purity contract) — the dependency runs the other way, so a
# new required section cannot be added to the validator without this
# migration's `_ALL_REQUIRED_SECTIONS` (derived below) knowing about it too.
REQUIRED_CONFIG_SECTIONS = (
    "project", "commands", "review", "runner", "git", "nightshift_state", "release_policy",
)
CFG_RUNNER_POLICY_SECTIONS = (
    "runner", "parallel_admission", "circuit_breaker", "review", "git",
    "nightshift_state", "release_policy", "watcher", "metrics",
)

# The schema version SPEC-269's registered migration brings an install up to.
# Keep in sync with `schema_version:` in canonical/config.yaml (SPEC-269 R1/R3).
TARGET_SCHEMA_VERSION = "3.1.0"

# The schema version SPEC-327's registered migration brings an install up to.
# `migrate()` defaults to this — the newest registered target.
LATEST_SCHEMA_VERSION = "3.2.0"

# Exact starter defaults from canonical/config.yaml — see its `unblock:` and
# `resilience:` blocks. Keep byte-identical to that file's documented defaults.
_UNBLOCK_BLOCK = """\
# Opt-in drive-to-done ladder. The default unblock command does not read these
# values and retains its one bounded repair / blocked-to-ready behavior.
unblock:
  ac_review:
    max_loosened_per_pass: 2
  to_done:
    max_rung: 5
    dry_run: false
"""

_RESILIENCE_BLOCK = """\
# SPEC-266: class-specific recovery budgets are run-id keyed effects.
resilience:
  verifier_fail: {max_rounds: 2}
  premise: {enabled: true}
  evidence_gap: {max_passes: 1}
  transport: {max_rebinds: 2}
"""


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


def _has_top_level_key(text: str, key: str) -> bool:
    return re.search(rf"^{re.escape(key)}:", text, re.MULTILINE) is not None


def _current_schema_version(text: str) -> str | None:
    match = re.search(r'^schema_version:\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _append_block(text: str, block: str) -> str:
    prefix = text if text.endswith("\n") else text + "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return f"{prefix}---\n\n{block}"


def _set_schema_version(text: str, version: str) -> str:
    pattern = re.compile(r'^schema_version:\s*"[^"]+"', re.MULTILINE)
    replacement = f'schema_version: "{version}"'
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    # No existing field: prepend one rather than guessing a document boundary.
    prefix = replacement + "\n"
    if text and not text.startswith("\n"):
        prefix += "\n"
    return prefix + text


def add_resilience_and_unblock_blocks(text: str) -> str:
    """Migrate a project ``config.yaml`` to ``TARGET_SCHEMA_VERSION`` (SPEC-269).

    Adds the ``unblock.*`` and ``resilience.*`` blocks (documented starter
    defaults) only when each is absent, then sets ``schema_version`` to
    ``TARGET_SCHEMA_VERSION``. A config already at or above that schema version
    is returned unchanged. Pure and idempotent — see module docstring.
    """
    current = _current_schema_version(text)
    if current is not None and _version_tuple(current) >= _version_tuple(
        TARGET_SCHEMA_VERSION
    ):
        return text

    migrated = text
    if not _has_top_level_key(migrated, "unblock"):
        migrated = _append_block(migrated, _UNBLOCK_BLOCK)
    if not _has_top_level_key(migrated, "resilience"):
        migrated = _append_block(migrated, _RESILIENCE_BLOCK)
    return _set_schema_version(migrated, TARGET_SCHEMA_VERSION)


# --- SPEC-327: append every REQUIRED_CONFIG_SECTIONS/CFG_RUNNER_POLICY_SECTIONS
# section that is absent, so CFG.RUNNER_POLICY can no longer DENY a config
# that was bootstrapped before the section was required. Every block below is
# copied byte-identical from canonical/config.yaml's own starter defaults
# (which match config-reference.yaml's per-field `Default:` annotations) —
# never a project's filled-in value, and never config-reference.yaml's
# illustrative example values (some of which, e.g. `project.name:
# "multi-stack-example"`, are themselves placeholders validate_install.py
# would flag). A migration must never invent policy for a project.

_PROJECT_BLOCK = """\
project:
  name: ""                                # Short name, no spaces (e.g., "my-app", "tram-tracker")
  description: ""                         # One-line description of what this project does
  language: []                            # Primary languages: python, typescript, swift, rust, go, java, kotlin, etc.
"""

_COMMANDS_BLOCK = """\
commands:
  build: ""                         # REQUIRED — compile/build the project
  test: ""                          # REQUIRED — run the full test suite
  test_timeout_s: 300               # OPTIONAL — timeout for test execution in seconds (0 = no timeout, not recommended)
  lint: ""                          # REQUIRED — static analysis; configure to fail on warnings
  type_check: ""                    # REQUIRED for typed languages (tsc, mypy, pyright); "" if untyped
  format: ""                        # OPTIONAL — check formatting without changing files
  format_fix: ""                    # OPTIONAL — auto-fix formatting (agent uses this if format fails)
"""

_REVIEW_BLOCK = """\
review:
  mode: "self"                            # self | subagent | hybrid
  enabled: [architect, security, performance, domain, quality, user]
  extra_criteria: []
"""

_RUNNER_BLOCK = """\
runner:
  mode: "inline"                  # inline | orchestrator
  domain: "code"                  # code | research | analysis
  model_selection: "auto"         # auto | fixed
  harness: "claude-code"          # Logged in metrics for traceability
  tiers:
    tier-1:                              # Bugfix, simple features (<=3 ACs)
      model: ""                          # Fill in: e.g., "claude-haiku-4-5-20251001"
      harness: "claude-code"
    tier-2:                              # Features (4-8 ACs), complex bugfixes
      model: ""                          # Fill in: e.g., "claude-sonnet-4-6"
      harness: "claude-code"
    tier-3:                              # Architectural changes (9+ ACs, layer 3)
      model: ""                          # Fill in: e.g., "claude-opus-4-6"
      harness: "claude-code"
"""

_GIT_BLOCK = """\
git:
  main_branch: "main"             # main, develop, master — match your repo
  branch_prefix: "nightshift"     # Spec branches: nightshift/SPEC-001, etc.
  commit_style: "conventional"    # conventional (feat/fix/test/docs) | simple
  commit_prefix: "spec-id"        # spec-id: [SPEC-123] prefix | none: no prefix
  worktrees: "auto"               # auto: mandatory on concurrent paths; optional for single-agent inline
  merge_strategy: "no-ff"         # no-ff | squash | rebase
  merge_on_pass: true             # Merge to main_branch when tests pass and review approves
  diff_risk_threshold: 500         # Staged added-line count requiring explicit sign-off
  token_cost_threshold: 8000       # Approximate staged token-cost requiring explicit sign-off
  escalation_signoff_env: "NIGHTSHIFT_ESCALATION_SIGNOFF"
"""

_NIGHTSHIFT_STATE_BLOCK = """\
nightshift_state:
  policy: commit-backed                    # commit-backed | private-local
  private_paths: [".nightshift"]           # privacy-gated paths in private-local mode
"""

_RELEASE_POLICY_BLOCK = """\
release_policy:
  committed_kit: allow                    # allow | opt_out
"""

_PARALLEL_ADMISSION_BLOCK = """\
parallel_admission:
  worker_limit: 1                 # Maximum active worktree workers
  missing_touches_policy: "exclusive"  # exclusive | allow
"""

_CIRCUIT_BREAKER_BLOCK = """\
circuit_breaker:
  max_same_error: 3               # Consecutive identical build/test errors
  max_review_cycles: 5            # Review rounds per spec
  max_spec_duration_min: 120      # Hard ceiling per spec (minutes). Increase for slow builds.
  phase_duration_multiplier: 3    # Stall if phase takes Nx the running average
"""

_WATCHER_BLOCK = """\
watcher:
  enabled: false
  poll_interval_min: 5            # How often to check for new commits
  idle_timeout_min: 30            # Stop if no new commits for this long
  review_file: "WATCHER-REVIEW.md"
  lens: "general"                 # general | code | security | ux | legal | performance
"""

_METRICS_BLOCK = """\
metrics:
  enabled: true
  track: [duration, test_results, review_cycles, build_errors, files_changed]
"""

# Section name -> its documented safe-default block, appended only when the
# section's top-level key is absent from the config being migrated.
_REQUIRED_SECTION_BLOCKS: dict[str, str] = {
    "project": _PROJECT_BLOCK,
    "commands": _COMMANDS_BLOCK,
    "review": _REVIEW_BLOCK,
    "runner": _RUNNER_BLOCK,
    "git": _GIT_BLOCK,
    "nightshift_state": _NIGHTSHIFT_STATE_BLOCK,
    "release_policy": _RELEASE_POLICY_BLOCK,
    "parallel_admission": _PARALLEL_ADMISSION_BLOCK,
    "circuit_breaker": _CIRCUIT_BREAKER_BLOCK,
    "watcher": _WATCHER_BLOCK,
    "metrics": _METRICS_BLOCK,
}

# Ordered union of REQUIRED_CONFIG_SECTIONS and CFG_RUNNER_POLICY_SECTIONS —
# the exact set validate_install.py's CFG.RUNNER_POLICY invariant (plus its
# plain required-sections check) can fail an install on. Order preserved,
# duplicates dropped.
_ALL_REQUIRED_SECTIONS: tuple[str, ...] = tuple(
    dict.fromkeys(REQUIRED_CONFIG_SECTIONS + CFG_RUNNER_POLICY_SECTIONS)
)


def add_required_config_sections(text: str) -> str:
    """Migrate a project ``config.yaml`` to schema ``3.2.0`` (SPEC-327).

    Appends every section in ``_ALL_REQUIRED_SECTIONS`` that is absent, using
    its documented safe default (see the block constants above), then sets
    ``schema_version`` to ``"3.2.0"``. Additive only — an already-present
    section (even a project-customized one) is left byte-for-byte untouched.
    A config already at or above schema 3.2.0 is returned unchanged. Pure and
    idempotent, same contract as ``add_resilience_and_unblock_blocks``.
    """
    current = _current_schema_version(text)
    if current is not None and _version_tuple(current) >= _version_tuple("3.2.0"):
        return text

    migrated = text
    for section in _ALL_REQUIRED_SECTIONS:
        if not _has_top_level_key(migrated, section):
            migrated = _append_block(migrated, _REQUIRED_SECTION_BLOCKS[section])
    return _set_schema_version(migrated, "3.2.0")


# Registry: target schema_version -> pure migration function. A worker (or
# release_coordinator.default_migration_runner) looks up the manifest's
# required `schema_version` here to find the one registered, deterministic
# transformation it must apply — never a freeform edit. `migrate()` below
# chains every registered step up to and including the requested target, in
# ascending version order, so an install several schema versions behind
# receives each intermediate step in order (SPEC-327 R2).
MIGRATIONS: dict[str, "callable[[str], str]"] = {
    TARGET_SCHEMA_VERSION: add_resilience_and_unblock_blocks,
    LATEST_SCHEMA_VERSION: add_required_config_sections,
}


KIT_VERSION_LINE = re.compile(r'^(kit_version:\s*")[^"]*(")', re.MULTILINE)


def set_kit_version(text: str, version: str) -> str:
    """Rewrite only the quoted value on an existing ``kit_version:`` line.

    BUG-326: the whole-kit release never updated an install's project-owned
    ``kit_version``, so every delivered install failed admission on
    ``CFG.PARSE_VERSION`` and ``KIT.MARKER`` the moment the release landed.
    This is SPEC-127's ``write_kit_version`` semantics moved into managed
    payload: no other byte changes, and text without the line is returned
    unchanged (the config validator already reports the missing key).
    """
    return KIT_VERSION_LINE.sub(lambda m: f"{m.group(1)}{version}{m.group(2)}", text, count=1)


def migrate(text: str, *, target: str = LATEST_SCHEMA_VERSION) -> str:
    """Apply every registered migration up to and including ``target``.

    Raises ``ValueError`` if ``target`` itself is not a registered schema
    version — a worker must never invent an ad hoc transformation for an
    unregistered schema version. Otherwise, walks the registered targets in
    ascending version order and applies each one's function in turn (SPEC-327
    R2): a config several schema versions behind receives every intermediate
    step, in order, in one call. Each registered function already no-ops once
    a config is at or above its own target, so this is idempotent and
    monotone — calling it twice, or calling it once instead of stepwise, is
    byte-identical.
    """
    if target not in MIGRATIONS:
        raise ValueError(f"no registered config migration for schema {target!r}")
    result = text
    for version in sorted(MIGRATIONS, key=_version_tuple):
        if _version_tuple(version) > _version_tuple(target):
            break
        result = MIGRATIONS[version](result)
    return result
