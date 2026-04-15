---
id: SPEC-BUG-093
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

# Direction toggle buttons have no border-radius, design specifies rounded group

## Problem

The direction toggle buttons ("All", "REQ →", "← RES") have `border-radius: 0px` on each button. The design shows a toggle group with rounded outer corners (the first and last buttons should have rounded left/right corners respectively), forming a pill-shaped button group.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Direction toggle group should have rounded outer corners matching the design's toggle/button-group pattern.

## Reproduction

1. Open Timeline tab, inspect the direction toggle buttons in the filter bar
2. **Actual:** All three buttons have border-radius 0px — square corners
3. **Expected:** First button has rounded left corners, last button has rounded right corners (pill group)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Toggle group container or first/last buttons have appropriate border-radius
- [ ] R2: First button has `border-radius: var(--radius-s) 0 0 var(--radius-s)` (or similar)
- [ ] R3: Last button has `border-radius: 0 var(--radius-s) var(--radius-s) 0`

## Acceptance Criteria

- [ ] AC 1: Toggle group appears as a pill-shaped group with rounded outer corners
- [ ] AC 2: Middle button(s) retain square corners
- [ ] AC 3: Active state styling still works correctly
- [ ] AC 4: `go build ./...` passes

## Context

- Live: All buttons padding 4px 12px, fontSize 11px, fontWeight 500, borderRadius 0px
- Active button: bg rgb(31, 111, 235), color white
- Inactive: transparent bg, color text-muted

## Out of Scope

- Toggle button font-size or padding
- Active state color

## Code Pointers

- `internal/web/ui/ds.css` — `.btn-group`, `.toggle-group`, or direction toggle rules
- `internal/web/ui/index.html` — direction toggle HTML structure

## Gap Protocol

- Research-acceptable gaps: exact design border-radius value for toggle groups
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
