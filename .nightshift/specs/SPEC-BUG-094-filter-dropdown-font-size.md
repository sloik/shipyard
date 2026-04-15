---
id: SPEC-BUG-094
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

# Filter dropdowns font-size is 13px, design specifies 12px

## Problem

The Server and Method `<select>` dropdowns in the filter bar render at `font-size: 13px`. The UX-002 design specifies `fontSize: 12` for dropdown values (`fMethodVal`, `fServerVal`).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** `fMethodVal` (kNzTi) has `fontSize: 12`, `fontWeight: normal`.

## Reproduction

1. Open Timeline tab, inspect a filter dropdown (Server or Method)
2. **Actual:** font-size 13px
3. **Expected:** font-size 12px (`--font-size-base`)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Filter dropdowns use `font-size: var(--font-size-base)` (12px)

## Acceptance Criteria

- [ ] AC 1: `#filter-server` renders at 12px
- [ ] AC 2: `#filter-method` renders at 12px
- [ ] AC 3: Dropdown text is still readable
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — `fMethodVal` (kNzTi) `fontSize: 12`
- Live: select elements `fontSize: 13px`, padding 5px 10px (design: [6, 10])

## Out of Scope

- Dropdown padding (minor: 5px 10px vs 6px 10px)
- Lucide chevron-down icon on native select (browser limitation)

## Code Pointers

- `internal/web/ui/ds.css` — filter select styling (grep for `filter-server`, `filter-method`, or `select`)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
