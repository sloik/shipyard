---
id: SPEC-BUG-084
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

# Filter bar gap is 16px, design specifies 12px

## Problem

The filter bar uses `gap: 16px` between its child elements. The UX-002 design specifies `gap: 12` for the filter bar container.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Filter bar node `Ikqcl` has `gap: 12`.

## Reproduction

1. Open the Timeline tab with the filter bar visible
2. Inspect the gap between filter elements
3. **Actual:** gap is 16px
4. **Expected:** gap should be 12px

## Root Cause

The filter bar (`#filter-bar`) used the `.app-bar` class which had no explicit `gap`. The spacing between filter controls was provided by `justify-content: space-between`, not a gap value. Added a dedicated `#filter-bar { gap: 12px; }` rule in ds.css to match the UX-002 specification of `gap: 12`.

## Requirements

- [ ] R1: Filter bar uses `gap: 12px`

## Acceptance Criteria

- [ ] AC 1: `.filter-bar` (or equivalent) has `gap: 12px`
- [ ] AC 2: Filter elements are still properly spaced and usable
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `Ikqcl` — `gap: 12`
- Live computed: `gap: 16px`
- Bug location: `internal/web/ui/ds.css` — `.filter-bar` or equivalent selector

## Out of Scope

- Filter bar Clear button alignment (SPEC-BUG-083)
- Filter bar content or functionality

## Code Pointers

- `internal/web/ui/ds.css` — filter bar gap rule (grep for `filter-bar` or `.filter`)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
