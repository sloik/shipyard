---
id: SPEC-BUG-068
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

# Table header font-size is 10px (xs) instead of 11px (sm)

## Problem

The `.table-header > *` CSS rule sets `font-size: var(--font-size-xs)` (10px). The UX-002 design specifies `fontSize: 11` for all table header text nodes, which maps to `--font-size-sm` (11px).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header-row node (`iwPKi`), all header text nodes (`daZfq`, `ogKKi`, `eJ7N4`, `haA06`, `NBhsZ`, `o7wbr`) have `fontSize: 11`.

## Reproduction

1. Open the Timeline tab in Shipyard UI
2. Inspect any table header cell (Time, Dir, Server, etc.)
3. **Actual:** font-size is 10px (`--font-size-xs`)
4. **Expected:** font-size should be 11px (`--font-size-sm`)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: `.table-header > *` uses `font-size: var(--font-size-sm)` (11px)

## Acceptance Criteria

- [ ] AC 1: `.table-header > *` in `ds.css` specifies `font-size: var(--font-size-sm)`
- [ ] AC 2: All table headers across all views render at 11px
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `iwPKi` header text nodes all use `fontSize: 11`
- Token mapping: `--font-size-xs: 10px`, `--font-size-sm: 11px`
- Bug location: `internal/web/ui/ds.css`, `.table-header > *` rule (line ~998)

## Out of Scope

- Table header color (SPEC-BUG-056)
- Table header text-transform (SPEC-BUG-064)
- Table header letter-spacing (SPEC-BUG-069)

## Code Pointers

- `internal/web/ui/ds.css` — `.table-header > *` (line ~998, `font-size: var(--font-size-xs)`)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
