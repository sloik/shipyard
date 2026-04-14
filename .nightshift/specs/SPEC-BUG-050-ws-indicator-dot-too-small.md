---
id: SPEC-BUG-050
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-14
---

# WebSocket indicator dot is 6px instead of design-specified 8px

## Problem

The live/disconnected status indicator dot in the header renders at 6×6px. The UX-002 design specifies an 8×8px dot.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar right group, Indicator/Live component (`DNFbX`) contains an ellipse node (`ihVJB`) with `width: 8, height: 8`.

## Reproduction

1. Open any page in Shipyard UI
2. Inspect the `<span id="ws-indicator">` element's `::before` pseudo-element
3. **Actual:** dot is 6×6px
4. **Expected:** dot should be 8×8px per UX-002 design

## Root Cause

CSS typo: `.ws-indicator::before` in `ds.css` had `width: 6px; height: 6px` instead of the UX-002-specified 8px. One-line fix in the design system stylesheet.

## Requirements

- [x] R1: WebSocket indicator dot is 8×8px matching the UX-002 design

## Acceptance Criteria

- [x] AC 1: `.ws-indicator::before` has `width: 8px; height: 8px` in `ds.css`
- [x] AC 2: Dot remains circular (border-radius: 50%)
- [x] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `ihVJB` inside Indicator/Live component — `width: 8, height: 8, fill: #3fb950`
- Bug location: `internal/web/ui/ds.css`, `.ws-indicator::before` rule

## Out of Scope

- Indicator text styling
- Reconnecting animation behavior

## Code Pointers

- `internal/web/ui/ds.css` — `.ws-indicator::before` (line ~721)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
