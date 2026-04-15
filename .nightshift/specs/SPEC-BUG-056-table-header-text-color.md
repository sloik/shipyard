---
id: SPEC-BUG-056
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Table header text color uses --text-muted instead of --text-secondary

## Problem

All table headers across Timeline, History, and other views use `color: var(--text-muted)` (#8b949e). The UX-002 design specifies table header text fill as `#b1bac4`, which maps to the `--text-secondary` token.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header-row node (`iwPKi`) — child text nodes (`daZfq`, `ogKKi`, `eJ7N4`, `haA06`, `NBhsZ`, `o7wbr`) all have `fill: #b1bac4` (--text-secondary), not `#8b949e` (--text-muted).

## Reproduction

1. Open the Timeline tab in Shipyard UI
2. Inspect the table header row (Time, Dir, Server, Method, Status, Latency)
3. **Actual:** Header text color is `var(--text-muted)` (#8b949e)
4. **Expected:** Header text color should be `var(--text-secondary)` (#b1bac4)

## Root Cause

Wrong design token used during initial implementation. The `.table-header > *` rule in `ds.css` was written with `color: var(--text-muted)` (#8b949e) instead of `color: var(--text-secondary)` (#b1bac4). The UX-002 design spec (node `iwPKi`) clearly specifies `fill: #b1bac4` for all header-row child text nodes, which maps to `--text-secondary`. The two tokens are adjacent in lightness and easily confused without explicit reference to the design file.

## Requirements

- [x] R1: `.table-header > *` uses `color: var(--text-secondary)` instead of `var(--text-muted)`

## Acceptance Criteria

- [x] AC 1: `.table-header > *` rule in `ds.css` specifies `color: var(--text-secondary)`
- [x] AC 2: All table headers (Timeline, History, Tokens, Sessions, Performance) render in #b1bac4
- [x] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `iwPKi` (header-row) — child text nodes all use `fill: #b1bac4`
- Token mapping: `--text-secondary: #b1bac4`, `--text-muted: #8b949e`
- Bug location: `internal/web/ui/ds.css`, `.table-header > *` rule (line ~996–1004)

## Out of Scope

- Table header font-size, font-weight, or letter-spacing changes
- Table header sort indicators
- Column width adjustments

## Code Pointers

- `internal/web/ui/ds.css` — `.table-header > *` (line ~996)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
