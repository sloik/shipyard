---
id: SPEC-BUG-107
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

# Tabs missing top-corner border-radius

## Problem

Nav tabs render with no border-radius (square corners). The UX-002 design specifies `cornerRadius: [$radius-m, $radius-m, 0, 0]` — rounded top-left and top-right corners, square bottom corners.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tab shape should have rounded top corners per design component Tab/Default (node `3wZYe`).

## Reproduction

1. Open any page, inspect a nav tab
2. **Actual:** border-radius is 0 on all corners
3. **Expected:** top-left and top-right corners rounded (`$radius-m`), bottom corners square

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Apply `border-radius: var(--radius-m) var(--radius-m) 0 0` to tab elements

## Acceptance Criteria

- [ ] AC 1: Tabs have rounded top-left and top-right corners
- [ ] AC 2: Bottom corners remain square (0)
- [ ] AC 3: Active tab border-bottom is not affected by border-radius
- [ ] AC 4: `go build ./...` passes

## Context

- Design: Tab/Default component (node `3wZYe`): `cornerRadius: [$radius-m, $radius-m, 0, 0]`
- `$radius-m` resolves to the medium radius token (likely 6px based on DS)
- Live: tabs have no border-radius at all
- This applies to both active and default tab states

## Out of Scope

- Tab font-size (SPEC-BUG-104)
- Tab padding/height (SPEC-BUG-106)
- Tab label text (SPEC-BUG-102)

## Code Pointers

- `internal/web/ui/ds.css` — `.tab` rule (add border-radius)

## Gap Protocol

- Research-acceptable gaps: exact value of `$radius-m`
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
