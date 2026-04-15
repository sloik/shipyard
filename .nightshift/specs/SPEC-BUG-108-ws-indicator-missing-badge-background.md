---
id: SPEC-BUG-108
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

# WS indicator is plain text, design shows colored badge

## Problem

The WebSocket status indicator (Live / Disconnected / Reconnecting) in the header right area renders as plain text with a colored dot. The UX-002 design shows it as a colored badge with a background fill, matching the badge pattern used elsewhere in the UI.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** WS indicator should render as a colored badge (background + text), not plain text with a dot.

## Reproduction

1. Open any page, look at the WS indicator in the header right area
2. **Actual:** Small colored dot + plain text ("Live" / "Disconnected"), no background
3. **Expected:** Colored badge pill with background (e.g., success-subtle bg for "Live", danger-subtle bg for "Disconnected")

## Root Cause

`.ws-indicator` had correct dot/text styling from BUG-077/078 but no `padding`, `border-radius`, or background colors on the state classes. Adding `padding: 2px 8px` and `border-radius: var(--radius-full)` to the base rule plus semitransparent background fills to each state class produces the badge pill shape.

## Requirements

- [x] R1: WS indicator renders as a badge with colored background
- [x] R2: `.ws-live` uses `$success-subtle` background, `$success-fg` text
- [x] R3: `.ws-disconnected` uses `$danger-subtle` background, `$danger-fg` text
- [x] R4: `.ws-reconnecting` uses `$warning-subtle` background, `$warning-fg` text

## Acceptance Criteria

- [x] AC 1: "Live" state shows as green badge pill (success-subtle bg)
- [x] AC 2: "Disconnected" state shows as red badge pill (danger-subtle bg)
- [x] AC 3: "Reconnecting" state shows as yellow/orange badge pill (warning-subtle bg)
- [x] AC 4: Badge has appropriate padding and border-radius (pill shape)
- [x] AC 5: `go build ./...` passes

## Context

- Design: WS indicator in header right area is a colored badge component
- Live: `.ws-indicator` in ds.css (lines ~720-751) has correct font-size/weight/gap but lacks badge background styling
- The dot indicator can remain if desired, but the background fill is required per design
- Padding should be approximately `2px 8px` with `border-radius: var(--radius-full)` to match badge pattern

## Out of Scope

- WS reconnection logic
- WS indicator text content

## Code Pointers

- `internal/web/ui/ds.css` — `.ws-indicator`, `.ws-live`, `.ws-disconnected`, `.ws-reconnecting` rules
- `internal/web/ui/index.html` — WS indicator element in header right area

## Gap Protocol

- Research-acceptable gaps: exact design token values for badge backgrounds
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
