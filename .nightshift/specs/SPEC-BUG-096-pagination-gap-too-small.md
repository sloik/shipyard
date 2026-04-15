---
id: SPEC-BUG-096
template_version: 2
priority: 3
layer: 2
type: bugfix
status: superseded
superseded_by: SPEC-BUG-113
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Pagination bar gap is 4px, design specifies 12px

## Problem

The `.pagination` bar's internal gap between child elements is `4px`. The UX-002 design specifies `gap: 12` for the pagination row (`Wp0K8`), giving proper spacing between the info badge, page numbers, and nav buttons.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Pagination row `gap: 12`, `justifyContent: center`, `padding: [8,16]`.

## Reproduction

1. Open Timeline tab, scroll to the pagination bar at the bottom
2. Inspect `.pagination` — `gap: 4px`
3. **Actual:** 4px gap — elements are cramped
4. **Expected:** 12px gap between pagination elements

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Pagination bar uses `gap: 12px`
- [ ] R2: Pagination content is centered (`justify-content: center`)

## Acceptance Criteria

- [ ] AC 1: `.pagination` has `gap: 12px`
- [ ] AC 2: Pagination elements are visually well-spaced
- [ ] AC 3: Pagination still fits within the viewport width
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — `Wp0K8` pagination: `gap: 12`, `justifyContent: center`, `padding: [8,16]`
- Live: `.pagination { gap: 4px; padding: 10px 16px }`
- Also: `.pagination-nav` gap may need updating

## Out of Scope

- Page number button styling (borderRadius, sizing)
- Prev/Next button padding
- "Go to" jump input (not yet implemented)

## Code Pointers

- `internal/web/ui/ds.css` — `.pagination` rules
- `internal/web/ui/index.html` — pagination HTML

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
