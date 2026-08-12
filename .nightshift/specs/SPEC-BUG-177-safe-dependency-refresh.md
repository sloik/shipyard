---
id: SPEC-BUG-177
template_version: 7
priority: 2
layer: 2
type: refactor
status: draft
parent: SPEC-BUG-171
after: [SPEC-BUG-172, SPEC-BUG-173, SPEC-BUG-174, SPEC-BUG-175, SPEC-BUG-176]
nfrs: [SPEC-NFR-001]
created: 2026-08-12
stack: go
devkb_required: ["go.md", "testing.md", "security.md"]
---

# Refresh safe Shipyard dependencies after MCP migration

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

- Wails beta (SPEC-BUG-178) and child Python/Go runtime updates.

