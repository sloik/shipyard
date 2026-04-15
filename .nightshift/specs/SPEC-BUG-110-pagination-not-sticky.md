---
id: SPEC-BUG-110
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

# Pagination bar scrolls out of view — should be sticky at bottom

## Problem

The pagination bar (`.pagination`) in the Traffic Timeline view is `position: static` inside a scrollable container (`#view-timeline` with `overflow: auto`). When the table has enough rows, the pagination scrolls off-screen and the user must scroll to the very bottom to access it. The UX-002 design shows pagination pinned at the bottom of the viewport, always visible.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Pagination bar should be persistently visible at the bottom of the view, not scrolled away with content.

## Reproduction

1. Open the Traffic tab with enough entries to cause scrolling (e.g., 25+ rows)
2. Scroll up in the table
3. **Actual:** Pagination disappears below the fold
4. **Expected:** Pagination stays pinned at the bottom, always accessible

## Root Cause

`.pagination` in ds.css (line ~1620) had no `position: sticky` rule. The route view (`.route-view`) uses `overflow: auto`, making it the scrollable ancestor for both `#view-timeline` and `#view-history`. Because `.pagination` is a descendant of `.route-view`, adding `position: sticky; bottom: 0` to `.pagination` is sufficient — the element sticks to the bottom of its nearest scrollable ancestor (the `.route-view` container) without any structural changes. The `background: var(--bg-surface)` was already present and opaque, so no additional background fix was needed.

## Requirements

- [x] R1: Pagination bar is sticky at the bottom of its scrollable parent
- [x] R2: Pagination remains visible regardless of scroll position
- [x] R3: This applies to all views with pagination (Timeline, History)

## Acceptance Criteria

- [x] AC 1: Pagination bar is always visible at the bottom of the Traffic view
- [x] AC 2: Pagination bar is always visible at the bottom of the History view
- [x] AC 3: Table content scrolls behind/above the pagination
- [x] AC 4: Pagination background is opaque (no content bleeding through)
- [x] AC 5: `go build ./...` passes

## Context

- Design: Pagination/Bar component (`RFK8O`) is at the very bottom of the Traffic Timeline frame (`rRx2E`), always visible
- Live: `.pagination` at ds.css line ~1613, `position: static`, `background: var(--surface-overlay)`, `border-top: 1px solid var(--border-default)`
- Live: `#view-timeline` has `overflow: auto`, `scrollHeight: 1327 > offsetHeight: 1121`
- Fix approach: use `position: sticky; bottom: 0;` on `.pagination`, ensure `background` is opaque, and the route-view structure supports sticky positioning
- Alternative: restructure route-view as flex column with table in a scrollable area and pagination outside it

## Out of Scope

- Pagination styling (gap, colors — already covered by BUG-096, BUG-097, BUG-063)
- Table row styling

## Code Pointers

- `internal/web/ui/ds.css` — `.pagination` rule (line ~1613), `.route-view` rules
- `internal/web/ui/index.html` — `#view-timeline` structure, pagination placement

## Gap Protocol

- Research-acceptable gaps: whether sticky works within the current overflow:auto container or needs structural change
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
