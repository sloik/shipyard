---
id: SPEC-BUG-106
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

# Tab padding and height don't match design

## Problem

Nav tabs have `padding: 10px 12px` and computed height ~41.5px. The UX-002 design specifies `padding: [0, 12]` (0 top/bottom, 12 left/right) and `height: 48px` on the tab container.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tab dimensions should match design: padding 0 12px, height 48px.

## Reproduction

1. Open any page, inspect a nav tab
2. **Actual:** padding 10px 12px, height ~41.5px
3. **Expected:** padding 0 12px, height 48px

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Tab padding changed to `0 12px` (vertical padding removed, horizontal stays 12px)
- [ ] R2: Tab height set to 48px (use line-height or explicit height)

## Acceptance Criteria

- [ ] AC 1: Tab horizontal padding is 12px
- [ ] AC 2: Tab vertical padding is 0
- [ ] AC 3: Tab height is 48px
- [ ] AC 4: Tab text remains vertically centered
- [ ] AC 5: Active tab border-bottom still visible at bottom edge
- [ ] AC 6: `go build ./...` passes

## Context

- Design: Tab/Default component (node `3wZYe`): `padding: [0, 12]`, `height: 48`
- Live: `.tab` class has `padding: 10px 12px`, computed height ~41.5px
- The active-tab 2px border-bottom needs to remain at the bottom of the 48px height
- Both active (fontWeight 600) and default (fontWeight 500) tabs need this fix

## Out of Scope

- Tab font-size (SPEC-BUG-104)
- Tab border-radius (SPEC-BUG-107)
- Tab label text (SPEC-BUG-102)

## Code Pointers

- `internal/web/ui/ds.css` — `.tab` rule (padding, height/line-height)
- `internal/web/ui/index.html` — nav tab links

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
