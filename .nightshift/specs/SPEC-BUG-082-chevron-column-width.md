---
id: SPEC-BUG-082
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

# Chevron/expand column renders at 32px wide, design specifies 24px

## Problem

The `[data-col="chevron"]` column is set to `width: 14px` in CSS, but due to cell padding (`8px 16px`), the actual rendered width is ~32px. The UX-002 design specifies the chevron column should be 24px total width.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Chevron column in the data row — design width is 24px.

## Reproduction

1. Open the Timeline tab with traffic data
2. Inspect the chevron column width (first column of each row)
3. **Actual:** Rendered width ~32px (14px content + padding)
4. **Expected:** Total column width 24px

## Root Cause

`[data-col="chevron"]` had `width: 14px` but inherited `padding: 8px 16px` from `.table-row > *`, adding 32px of horizontal padding for a total rendered width of ~46px. Fix: override the chevron column to `width: 24px; padding: 0; display: flex; align-items: center; justify-content: center;` so total width equals exactly 24px with the icon centered.

## Requirements

- [x] R1: Chevron column total rendered width is 24px
- [x] R2: Reduce or eliminate horizontal padding for the chevron column

## Acceptance Criteria

- [x] AC 1: `[data-col="chevron"]` renders at 24px total width
- [x] AC 2: Chevron icon is still centered within the column
- [x] AC 3: Row click/expand functionality is not affected
- [x] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — chevron column width 24px
- Live computed: `width: 14px` CSS, but rendered ~32px due to `padding: 8px 16px` inherited from `.table-row > *`
- Bug location: `internal/web/ui/ds.css` — `[data-col="chevron"]` (line ~1014)

## Out of Scope

- Chevron icon type (Unicode ▶ → Lucide is SPEC-BUG-057)
- Other column widths

## Code Pointers

- `internal/web/ui/ds.css` — `[data-col="chevron"]` (line ~1014), `.table-row > *` padding (line ~1024)

## Gap Protocol

- Research-acceptable gaps: exact padding values to achieve 24px total
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
