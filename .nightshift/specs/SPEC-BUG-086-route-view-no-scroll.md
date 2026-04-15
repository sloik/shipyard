---
id: SPEC-BUG-086
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Timeline and History tabs cannot scroll — content overflows viewport

## Problem

On the Timeline and History tabs (and potentially all tabs), the user cannot scroll to see content that extends beyond the viewport. The table renders all 25 paginated rows but if the content is taller than the browser window, no scrollbar appears and the bottom rows are cut off.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** All tab content must be scrollable within the viewport.

## Reproduction

1. Open Shipyard in a browser window (~1169px tall)
2. Navigate to Timeline or History tab with data
3. Try to scroll down to see lower rows or the pagination footer
4. **Actual:** No scroll — content is clipped, pagination may be invisible
5. **Expected:** Vertical scrollbar appears, user can scroll through all content

## Root Cause

`body` in ds.css uses `min-height: 100vh` instead of `height: 100vh`. With `min-height`, the body element grows beyond the viewport to accommodate all content (e.g., 4508px for a 1169px viewport). Even though `overflow: hidden` is set on body, the element itself is taller than the viewport. The flex children (`#app-chrome` → `#route-stack` → `.route-view`) inherit this unconstrained height, so the route-view's `overflow: auto` never triggers — `scrollHeight === clientHeight` because the container grew to fit all content.

**Fix:** Change `min-height: 100vh` to `height: 100vh` on `body`. This constrains the body to exactly the viewport height. The flex children with `flex: 1` are then constrained within this fixed height, and the route-view's `overflow: auto` engages when content exceeds the available space.

## Requirements

- [x] R1: `body` uses `height: 100vh` instead of `min-height: 100vh`
- [x] R2: Route views scroll vertically when content exceeds viewport

## Acceptance Criteria

- [x] AC 1: Timeline tab with 25+ rows shows a scrollbar and all rows are accessible
- [x] AC 2: History tab with data shows a scrollbar and all rows are accessible
- [x] AC 3: Pagination footer is visible (either by scrolling to it or by it being in view)
- [x] AC 4: Header (app-bar) remains fixed at top, not scrolled away
- [x] AC 5: All other tabs (Tools, Servers, Tokens) still render correctly
- [x] AC 6: `go build ./...` passes

## Context

- Body computed height was 4508px in a 1169px viewport — `min-height: 100vh` allowed growth
- `html { overflow: hidden }` prevents page-level scroll
- `#route-stack { overflow: hidden }` prevents stack-level scroll
- `.route-view { overflow: auto; flex: 1; min-height: 0 }` — should scroll but doesn't because parent is unconstrained
- Bug location: `internal/web/ui/ds.css` — `body` rule (line ~224)

## Out of Scope

- Pagination logic (page size, page count)
- Horizontal scroll
- Mobile/responsive layout

## Code Pointers

- `internal/web/ui/ds.css` — `body` (line ~224), `#app-chrome` (line ~237), `#route-stack` (line ~258), `.route-view` (line ~281)

## Gap Protocol

- Research-acceptable gaps: whether any tab relies on body growing beyond viewport
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
