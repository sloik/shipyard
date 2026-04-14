---
id: SPEC-BUG-046
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-14
---

# App bar height is 44px instead of design-specified 48px

## Problem

The main app bar (header) renders at 44px height. The UX-002 design specifies 48px.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar component (`wnzNq`) specifies `height: 48`.

## Reproduction

1. Open any page in Shipyard UI
2. Inspect the `<header class="app-bar">` element
3. **Actual:** computed height is 44px
4. **Expected:** height should be 48px per UX-002 design

## Root Cause

(Agent fills in during run.)

## Requirements

- [x] R1: App bar height matches the UX-002 design value of 48px

## Acceptance Criteria

- [x] AC 1: `.app-bar` has `height: 48px` in `ds.css`
- [x] AC 2: Tab items inside the app bar remain vertically centered
- [x] AC 3: `go build ./...` passes
- [x] AC 4: `go vet ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `wnzNq` (Header/AppBar), `height: 48`
- Bug location: `internal/web/ui/ds.css`, `.app-bar` rule

## Out of Scope

- Filter bar height (reuses `.app-bar` class but is a separate concern)
- Tab padding adjustments (separate spec if needed)

## Code Pointers

- `internal/web/ui/ds.css` — `.app-bar` rule
- `internal/web/ui/index.html` — `<header class="app-bar">`

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: if height change breaks layout of filter bar or other `.app-bar` users
- Max research subagents before stopping: 0
