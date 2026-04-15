---
id: SPEC-BUG-063
template_version: 2
priority: 2
layer: 2
type: bugfix
status: superseded
superseded_by: SPEC-BUG-113
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Pagination footer layout is centered instead of space-between with background and border

## Problem

The pagination footer (`.pagination`) centers its content with `justify-content: center`, has no background, and no top border. The UX-002 design specifies a footer with `justifyContent: space_between` (count text on left, page buttons on right), `fill: #161b22` (bg-surface background), `padding: [10,16]`, and a 1px top border (`#30363d` / border-default).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Footer node (`QQQNq`) — `justifyContent: "space_between"`, `fill: "#161b22"`, `padding: [10,16]`, `stroke: { thickness: { top: 1 }, fill: "#30363d" }`. Live CSS has `justify-content: center`, no background, no border-top, `padding: 12px`.

## Reproduction

1. Open the Timeline tab with enough traffic for pagination
2. Look at the pagination bar at the bottom
3. **Actual:** Content is centered, no background color, no top border, uniform 12px padding
4. **Expected:** "Showing X–Y of Z" text on the left, page buttons on the right (space-between), with `bg-surface` background and 1px top border in `--border-default`

## Root Cause

The `.pagination` rule in `ds.css` used `justify-content: center` with no background or border. The HTML child order also placed the page-info badge last (after buttons), so reordering was needed to achieve info-left / nav-right layout under `space-between`. A wrapper `.pagination-nav` div groups the Prev/page-nums/Next elements so `space-between` acts on two children: `#page-info` (left) and `.pagination-nav` (right).

## Requirements

- [x] R1: `.pagination` uses `justify-content: space-between`
- [x] R2: `.pagination` has `background: var(--bg-surface)`
- [x] R3: `.pagination` has `border-top: 1px solid var(--border-default)`
- [x] R4: `.pagination` padding is `10px 16px`

## Acceptance Criteria

- [x] AC 1: `.pagination` in `ds.css` has `justify-content: space-between`
- [x] AC 2: `.pagination` has `background: var(--bg-surface)`
- [x] AC 3: `.pagination` has `border-top: 1px solid var(--border-default)`
- [x] AC 4: `.pagination` has `padding: 10px 16px`
- [x] AC 5: Page info text ("Showing…") appears on the left, navigation buttons on the right
- [x] AC 6: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `QQQNq` (Footer) — `justifyContent: "space_between"`, `fill: "#161b22"`, `padding: [10,16]`, `stroke: { top: 1, fill: "#30363d" }`
- Bug location: `internal/web/ui/ds.css`, `.pagination` rule (line ~1561)

## Out of Scope

- Page number button styling (covered by `.page-num` rules)
- Prev/Next button styling
- Pagination logic or page count

## Code Pointers

- `internal/web/ui/ds.css` — `.pagination` (line ~1561)
- `internal/web/ui/index.html` — `<div id="pagination" class="pagination">` (line ~136)

## Gap Protocol

- Research-acceptable gaps: whether HTML structure of pagination needs reordering for space-between to look correct
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
