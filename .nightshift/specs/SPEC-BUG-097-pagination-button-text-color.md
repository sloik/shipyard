---
id: SPEC-BUG-097
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

# Pagination Prev/Next button text is text-primary, design specifies text-secondary

## Problem

The pagination "← Prev" and "Next →" buttons render with `color: rgb(230, 237, 243)` (`--text-primary`). The UX-002 design specifies `fill: $text-secondary` (#b1bac4) for these button labels (`prevLbl`, `nextLbl` inside `Wp0K8`).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Pagination prev/next labels use `$text-secondary` (#b1bac4).

## Reproduction

1. Open Timeline tab, inspect the "← Prev" or "Next →" button in the pagination bar
2. **Actual:** color `rgb(230, 237, 243)` = `#e6edf3` (text-primary) — too bright
3. **Expected:** color `#b1bac4` (text-secondary)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Prev/Next button text uses `color: var(--text-secondary)`

## Acceptance Criteria

- [ ] AC 1: "← Prev" button text renders at #b1bac4
- [ ] AC 2: "Next →" button text renders at #b1bac4
- [ ] AC 3: Buttons are still clearly clickable/readable
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — `CuSEP` (prevLbl) and `DsTk6` (nextLbl) both `fill: $text-secondary`
- Live: `.btn-default` has `color: var(--text-primary)` which is #e6edf3
- The buttons also have `padding: 3px 8px` vs design `padding: [6,12]` — minor, out of scope

## Out of Scope

- Button padding (3px 8px vs 6px 12px)
- Page number button styling
- Pagination gap (SPEC-BUG-096)

## Code Pointers

- `internal/web/ui/ds.css` — `.btn-default` or `.pagination-nav .btn` rules
- `internal/web/ui/index.html` — pagination buttons

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
