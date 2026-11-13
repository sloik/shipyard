---
id: SPEC-BUG-186
template_version: 7
priority: 2
layer: 2
type: refactor
status: draft
parent: SPEC-BUG-180
after:
- SPEC-BUG-181
- SPEC-BUG-182
- SPEC-BUG-183
- SPEC-BUG-184
- SPEC-BUG-185
nfrs:
- SPEC-NFR-001
created: 2026-08-12
stack: go
devkb_required:
- go.md
- testing.md
- security.md
---

# Refresh safe Shipyard dependencies after MCP migration

> Former ID: SPEC-BUG-177 (renumbered by SPEC-BUG-179 on 2026-10-03 to remove a duplicate ID).

## Problem

Protocol work will touch core runtime dependencies. Mixing unrelated updates obscures regressions; current safe candidates include coder/websocket, ncruces SQLite/WASM, and Playwright, while Wails is a separate major-risk migration.

## Requirements

- [ ] Inventory outdated/vulnerable Go/Node modules and classify direct, transitive, safe, breaking and unused dependencies.
- [ ] Upgrade only compatible non-Wails dependencies in small verified groups; remove dependencies proven unused after dual-era work.
- [ ] Run vulnerability/license, full unit/integration, race, coverage, packaging, browser and live gateway smoke gates after each group.
- [ ] Record exact rollback revisions and observable binary/startup changes.

## Acceptance Criteria

- [ ] AC1: Dependency manifests/locks are reproducible and contain no unexplained change.
- [ ] AC2: All configured quality gates, packaged app/bridge build and mixed-era live smoke pass.
- [ ] AC3: Wails remains unchanged and any deferred major has its own spec.

## Out of Scope

- Wails beta (SPEC-BUG-187) and child Python/Go runtime updates.


## State rationale

```yaml
schema_version: 1
status: draft
reason: Drafted 2026-08-12 as a child of the MCP 2026 migration plan (SPEC-BUG-180); not yet reviewed for promotion.
reconsider_when: SPEC-BUG-180 is promoted and every spec this one depends on is done, or the plan is replanned.
evidence: []
provenance: authored
record: artifacts/20261003T153225Z-decision-state-rationale-authored-draft-drafted-2.json
```
