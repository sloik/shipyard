---
id: SPEC-BUG-117
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Filter dropdowns use font-size 12px, design specifies 13px

## Problem

The filter bar dropdowns (`#filter-server`, `#filter-method`) use `font-size: 12px` (`--font-size-base`). The UX-002 design Input/Default component (`eKqw4`) specifies `fontSize: 13` — that's `--font-size-md` (13px). Select inputs should use the same size as text inputs.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Select/input elements should use `--font-size-md` (13px).

## Reproduction

1. Open the Traffic tab, inspect the "All servers" or "All methods" dropdown
2. **Actual:** font-size: 12px
3. **Expected:** font-size: 13px

## Root Cause

`#filter-server, #filter-method` had an explicit `font-size: var(--font-size-base)` rule in `ds.css` (lines 511–514) that overrode the `.field select` rule which correctly uses `var(--font-size-md)`. Changed to `var(--font-size-md)`.

## Requirements

- [x] R1: Filter select elements use `font-size: var(--font-size-md)` (13px)

## Acceptance Criteria

- [x] AC 1: Server filter dropdown renders at 13px
- [x] AC 2: Method filter dropdown renders at 13px
- [x] AC 3: Any other select/input elements in filter bars also use 13px
- [x] AC 4: `go build ./...` passes

## Context

- Design: Input/Default (`eKqw4`): fontSize 13, padding [12,8,12,8], cornerRadius [6,6,6,6]
- Live: selects at 12px, padding 5px 10px, borderRadius 6px
- Note: padding also differs (5px 10px vs 8px 12px) but that can be a separate fix
- Fix: change select font-size from `--font-size-base` to `--font-size-md`

## Out of Scope

- Select padding (minor, can be a follow-up)
- Select border/background colors

## Code Pointers

- `internal/web/ui/ds.css` — `select` or `.input-group select` rule

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
