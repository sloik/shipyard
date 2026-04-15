---
id: SPEC-BUG-114
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

# Table header cells use font-size 11px, design specifies 12px

## Problem

Table header cells (`.table-header > *`) use `font-size: var(--font-size-sm)` which resolves to 11px. The UX-002 design Table/HeaderRow component (`bPs7c`) specifies `fontSize: 12` — that's `--font-size-base` (12px).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Table header text should be 12px, not 11px.

## Reproduction

1. Open the Traffic tab, inspect any table header cell (Time, Dir, Server, etc.)
2. **Actual:** font-size: 11px
3. **Expected:** font-size: 12px

## Root Cause

`ds.css` line ~1060: `.table-header > *` sets `font-size: var(--font-size-sm)` (11px). Should be `var(--font-size-base)` (12px).

## Requirements

- [x] R1: Table header cells use `font-size: var(--font-size-base)` (12px)

## Acceptance Criteria

- [x] AC 1: Table header cells in Traffic Timeline render at 12px
- [x] AC 2: Table header cells in History Requests render at 12px
- [x] AC 3: Header text remains weight 600, color text-secondary
- [x] AC 4: `go build ./...` passes

## Context

- Design: Table/HeaderRow (`bPs7c`): fontSize 12, fontWeight 600, textColor #b1bac4
- Live: `.table-header > *` at ds.css ~1060: `font-size: var(--font-size-sm)` = 11px
- Fix: change `--font-size-sm` to `--font-size-base` in that rule

## Out of Scope

- Table data row font-size (already 12px, correct)
- Table header background or padding

## Code Pointers

- `internal/web/ui/ds.css` — `.table-header > *` rule (line ~1060)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
