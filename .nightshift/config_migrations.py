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

# The schema version this module's registered migration brings an install up to.
# Keep in sync with `schema_version:` in canonical/config.yaml (SPEC-269 R1/R3).
TARGET_SCHEMA_VERSION = "3.1.0"

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


# Registry: target schema_version -> pure migration function. A worker (or
# release_coordinator.default_migration_runner) looks up the manifest's
# required `schema_version` here to find the one registered, deterministic
# transformation it must apply — never a freeform edit.
MIGRATIONS: dict[str, "callable[[str], str]"] = {
    TARGET_SCHEMA_VERSION: add_resilience_and_unblock_blocks,
}


def migrate(text: str, *, target: str = TARGET_SCHEMA_VERSION) -> str:
    """Apply the registered migration for ``target`` to ``text``.

    Raises ``ValueError`` if no migration is registered for ``target`` — a
    worker must never invent an ad hoc transformation for an unregistered
    schema version.
    """
    fn = MIGRATIONS.get(target)
    if fn is None:
        raise ValueError(f"no registered config migration for schema {target!r}")
    return fn(text)
