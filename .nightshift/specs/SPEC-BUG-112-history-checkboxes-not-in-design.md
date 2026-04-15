---
id: SPEC-BUG-112
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

# History tab rows have checkboxes that are not in the design

## Problem

Each row in the History → Requests sub-view has an `<input type="checkbox" class="history-check">` as the first cell. The UX-002 design does not include checkboxes in any table row — neither in the Traffic Timeline nor in any History view. There are 100 checkbox inputs on the page with no associated bulk-action UI.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Table rows should not have checkboxes — design shows: Time, Dir, Server, Method, Status, Latency columns only.

## Reproduction

1. Navigate to History → Requests tab
2. **Actual:** Each row has a checkbox as the first column
3. **Expected:** No checkboxes; rows match the Traffic Timeline column layout

## Root Cause

The `historyRenderRow` function in `internal/web/ui/index.html` included a `<input type="checkbox" class="history-check">` as the first `<span>` in every history row, backed by a `historyChecked` state object and a "Compare (0/2)" button. This was likely scaffolded for a planned bulk-delete or compare feature that was never fully implemented. No bulk-action toolbar, select-all, or visible purpose existed for these checkboxes. The design (UX-002) specifies only Time, Dir, Server, Method, Status, Latency columns — no checkbox column.

## Requirements

- [x] R1: Remove `<input type="checkbox" class="history-check">` from history request rows
- [x] R2: Remove any associated checkbox column header if present

## Acceptance Criteria

- [x] AC 1: History Requests rows have no checkboxes
- [x] AC 2: Row layout matches Traffic Timeline (Time, Dir, Server, Method, Status, Latency)
- [x] AC 3: No orphaned checkbox-related JS/CSS remains
- [x] AC 4: `go build ./...` passes

## Context

- Live: 100 `<input type="checkbox" class="history-check">` elements inside `#history-requests-view .table-row` rows
- Each checkbox is the first child `<span>` of the row
- No bulk-action toolbar or "select all" UI exists — the checkboxes serve no visible purpose
- Design Table/DataRow component (`57Rlu`) has no checkbox column

## Out of Scope

- History row styling (font, colors)
- History sub-nav tabs (Requests/Sessions/Performance)

## Code Pointers

- `internal/web/ui/index.html` — JS that generates history rows (search for `history-check`)
- CSS for `.history-check` if any

## Gap Protocol

- Research-acceptable gaps: whether checkboxes were planned for a future bulk-delete feature
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
