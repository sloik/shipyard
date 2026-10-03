---
id: SPEC-BUG-179
template_version: 12
priority: 1
layer: 0
type: refactor
status: done
after: []
nfrs: []
nfr_waivers:
- id: SPEC-NFR-001
  reason: Spec-file renames only; no Go code changes, so the data-race NFR cannot be affected.
prior_attempts: []
attachments: []
created: 2026-10-03
scope:
  write:
  - .nightshift/specs/SPEC-BUG-17*-*.md
  - .nightshift/specs/SPEC-BUG-18*-*.md
---

# Renumber the MCP 2026 migration spec family to remove duplicate IDs

## Problem

Seven spec IDs are each used by two different spec files:

| ID | MCP 2026 migration family (created 2026-08-12) | Traffic/proxy fix (created 2026-09-24) |
|---|---|---|
| SPEC-BUG-171 | mcp-2026-dual-era-migration (planned) | seg-toggle-all-filters-everything-out (done) |
| SPEC-BUG-172 | mcp-conformance-core (draft) | traffic-copy-button-copies-line-numbers (done) |
| SPEC-BUG-173 | child-era-negotiation (draft) | live-traffic-rows-miss-correlated-fields (done) |
| SPEC-BUG-174 | dual-era-stdio-bridge (draft) | request-rows-stay-pending-after-response (done) |
| SPEC-BUG-175 | stateless-http-endpoint (draft) | traffic-filter-bar-design-drift (done) |
| SPEC-BUG-176 | catalog-cache-subscriptions (draft) | traffic-empty-state-design-drift (done) |
| SPEC-BUG-177 | safe-dependency-refresh (draft) | runchild-loses-output-on-child-exit (done) |

The migration family's `after:` chain (for example SPEC-BUG-174 waits on
`[SPEC-BUG-172, SPEC-BUG-173]`) resolves against both files of each ID. Because
the Traffic fixes are `done`, a dependency check can treat the unstarted
migration specs as unblocked, and spec lookups, the board, and lifecycle
artifacts cannot tell the two specs apart.

The done Traffic/proxy fixes keep their IDs. Their IDs appear in commit
messages, lifecycle commits, Go sources and tests, UI files, the Makefile, and
the smoke test. The migration family is referenced only by its own spec files,
and only the plan commit `c5304b9` names its parent ID.

## Requirements

- [x] R1: Renumber the eight migration-family specs by a fixed offset of +9:
  171→180, 172→181, 173→182, 174→183, 175→184, 176→185, 177→186, 178→187.
  Update each file name and its `id:` frontmatter.
- [x] R2: Rewrite every `SPEC-BUG-171`…`SPEC-BUG-178` reference inside the eight
  migration-family files (frontmatter `after:`/`parent:` and body text) to the
  new IDs, so the family's dependency graph is unchanged apart from the numbers.
- [x] R3: Leave the seven done Traffic/proxy specs, every non-spec file, and
  git history untouched.
- [x] R4: Each renumbered spec records its former ID in its body, so a reader
  who finds the old ID in commit `c5304b9` can locate the spec.
- [x] R5: Keep each migration spec's lifecycle status and content otherwise
  unchanged, except for the `## State rationale` section that the validator
  requires once a spec file is treated as new (SPEC-357/358 backfill).

## Acceptance Criteria

- [x] AC1: No two spec files under `.nightshift/specs/` share an `id:` value
  (templates excluded).
- [x] AC2: `grep -lE 'SPEC-BUG-17[1-8]'` over the eight renumbered files
  returns nothing except their "Former ID" lines.
- [x] AC3: Every `after:` entry in the renumbered files resolves to exactly one
  spec file.
- [x] AC4: `git diff --stat` for the change shows only the eight renames, the
  edits inside those eight files, and this spec.
- [x] AC5: `python3 .nightshift/validate_specs.py .nightshift/specs` reports no
  new error compared with before the change.

## Context

- Migration family: `.nightshift/specs/SPEC-BUG-171-mcp-2026-dual-era-migration.md`
  and its children SPEC-BUG-172…178.
- The offset is +9 rather than +8 because SPEC-BUG-179 is this spec's own ID,
  issued by `check_followup_spec.py`.
- Active NFR reviewed: SPEC-NFR-001 (zero data races) does not apply; no Go
  code changes.

## Out of Scope

- Renumbering the done Traffic/proxy specs.
- Rewriting git history or commit messages.
- Any change to the migration family's requirements, ACs, or priorities.
- Reviewing whether SPEC-BUG-178 (now 187) is still needed after PR #36's
  Wails bump; that belongs to the migration work itself.

## State rationale

```yaml
schema_version: 1
status: done
reason: mechanical transition to 'done' via run coord-20261003-bug179
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261003T153238Z-status-transition-in-progress-done-mechanical-transition-t.json
```
