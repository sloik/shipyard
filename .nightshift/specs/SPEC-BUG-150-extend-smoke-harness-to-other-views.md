---
id: SPEC-BUG-150
template_version: 3
priority: 3
layer: 1
type: feature
status: draft
after: [SPEC-BUG-149]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Extend the headless smoke harness to other views (opt-in `make smoke-full`)

## Problem

SPEC-BUG-149 added a headless-browser smoke harness covering the Tool Browser's
interactive collapse behaviors. The same harness pattern (playwright-core +
system Chrome against a `--headless` instance) could catch interactive
regressions in other views (Traffic timeline expand/detail, History
select/replay, Servers cards, Tokens UI) that the Go source-scan tests cannot
see. Today only the Tool Browser is covered.

## Requirements

- [ ] R1: Additional smoke checks cover the key interactive behaviors of at
  least one more view (e.g. Traffic expand/collapse of a row detail).
- [ ] R2: The broader coverage is opt-in via a separate target (e.g.
  `make smoke-full`) so the fast `make smoke` stays quick for the common case.
- [ ] R3: Reuses the SPEC-BUG-149 harness scaffolding (server launch on
  ephemeral port, system Chrome, graceful skip when no browser).
- [ ] R4: Does not make the Go unit suite fail when a browser is unavailable.

## Acceptance Criteria

- [ ] AC1: `make smoke-full` runs the Tool Browser checks plus at least one
  additional view's interactive checks.
- [ ] AC2: `make smoke` remains the fast Tool-Browser-only path.
- [ ] AC3: New checks skip gracefully when no browser/node is present.
- [ ] AC4: README/Makefile documents `make smoke-full`.

## Context

Builds on `test/smoke/tool_browser_smoke.mjs`, the `make smoke` target, and the
ephemeral-port/teststubchild launch pattern from SPEC-BUG-149.

## Out of Scope

- Exhaustive coverage of every view; this is incremental expansion.
- Committing browser binaries.

## Gap Protocol

- Research-acceptable gaps:
  - Which view to cover first (pick the highest-interaction one).
- Stop-immediately gaps:
  - Making `go test ./...` depend on a browser.
- Max research subagents before stopping: 0
