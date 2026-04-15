---
id: SPEC-BUG-083
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

# Filter bar Clear button not pushed to right edge

## Problem

The filter bar's Clear button sits immediately after the direction toggle buttons with only a `gap` separating them. The UX-002 design has a spacer element (`fSpacer` with `width: fill_container`) between the direction toggle group and the Clear button, pushing Clear to the right edge of the filter bar.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Filter bar node `Ikqcl` — spacer `fSpacer` uses `width: fill_container` to push Clear button to the far right.

## Reproduction

1. Open the Timeline tab with filters visible
2. Look at the Clear button position
3. **Actual:** Clear button is adjacent to the direction toggles on the left side
4. **Expected:** Clear button is pushed to the far right edge of the filter bar

## Root Cause

The filter bar (`#filter-bar`) uses `.app-bar` which has `justify-content: space-between`, but the Clear button was not separated from the filter controls by any spacer. Adding `margin-left: auto` to `#clear-filters-btn` pushes it to the far right within the flex container, matching the UX-002 spacer intent.

## Requirements

- [ ] R1: Add a flexible spacer (e.g., `flex: 1`) between the filter controls and the Clear button
- [ ] R2: Clear button appears at the right edge of the filter bar

## Acceptance Criteria

- [ ] AC 1: Clear button is right-aligned within the filter bar
- [ ] AC 2: Filter controls (direction toggles, method filter, etc.) remain left-aligned
- [ ] AC 3: Layout still works when filter bar is narrower (responsive)
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `Ikqcl` — contains `fSpacer` with `width: fill_container` between direction group and Clear
- Live: Clear button at `internal/web/ui/index.html` line ~117, sits inline with other filter elements
- Bug location: `internal/web/ui/index.html` — filter bar structure (lines ~96-119)

## Out of Scope

- Clear button missing Lucide x icon (SPEC-BUG-058)
- Filter bar gap size (SPEC-BUG-084)

## Code Pointers

- `internal/web/ui/index.html` — filter bar (lines ~96-119, grep for `clear-filters-btn`)
- `internal/web/ui/ds.css` — `.filter-bar` layout rules

## Gap Protocol

- Research-acceptable gaps: whether spacer should be a div or margin-left:auto on Clear
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
