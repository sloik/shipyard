---
id: SPEC-BUG-088
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

# Status badges have padding 4px 10px, design specifies 2px 8px

## Problem

The `.badge` base class uses `padding: 4px 10px`. This was set by the BUG-076 fix for the server-count pill, but status badges (success, error, warning, info) in the design use smaller `padding: [2, 8]`. The server-count neutral badge correctly uses `4px 10px`, but status badges should be more compact.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Badge/Success (ddcEr), Badge/Error (GFcOr), Badge/Warning (nRsfA), Badge/Info (Nn4p6) all have `padding: [2, 8]`.

## Reproduction

1. Open Timeline tab, look at status badges ("ok", "pending", "error")
2. Inspect badge padding
3. **Actual:** padding 4px 10px (from `.badge` base rule)
4. **Expected:** padding 2px 8px for status badges

## Root Cause

The `.badge` base rule had `padding: 4px 10px` applied globally. This was appropriate for `.badge-neutral` (server-count pill) but was too large for the status variants. Fix: base rule lowered to `padding: 2px 8px`; `.badge-neutral` given an explicit `padding: 4px 10px` override to preserve its larger size.

## Requirements

- [x] R1: Status badges (`.badge-success`, `.badge-error`, `.badge-warning`, `.badge-info`) use `padding: 2px 8px`
- [x] R2: Server-count neutral badge retains `padding: 4px 10px`

## Acceptance Criteria

- [x] AC 1: Status badges render with padding 2px 8px
- [x] AC 2: `#server-count` (badge-neutral) retains padding 4px 10px
- [x] AC 3: Badges still display dot + text properly at smaller padding
- [x] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — Badge/Success `padding: [2, 8]`, Badge/Neutral `padding: [2, 8]` with stroke
- Note: Badge/Neutral in header (server-count) was explicitly designed at `padding: [4, 10]` — this is a different instance
- Live: `.badge { padding: 4px 10px }` (global)

## Out of Scope

- Badge dot size or gap (separate issue if needed)
- Badge font-size or font-weight

## Code Pointers

- `internal/web/ui/ds.css` — `.badge` base rule, `.badge-success`, `.badge-info`, etc.

## Gap Protocol

- Research-acceptable gaps: whether `.badge-neutral` in contexts other than server-count should be 2px 8px
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
