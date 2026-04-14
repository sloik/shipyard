---
id: SPEC-BUG-048
template_version: 2
priority: 2
layer: 2
type: bugfix
status: ready
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-14
---

# Missing vertical separator between brand name and tab navigation

## Problem

The app bar has no visual separator between the "Shipyard" brand text and the tab navigation. The UX-002 design shows a 1px wide × 20px tall vertical divider colored `#30363d` (border-default) between the brand and tabs.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar component (`wnzNq`) contains a separator rectangle node (`T6YLs`, name: "abSep") — a 1×20px rectangle with fill `#30363d`.

## Reproduction

1. Open any page in Shipyard UI
2. Look at the app bar between "Shipyard" text and the first tab
3. **Actual:** No separator; brand text flows directly into tab nav with just gap spacing
4. **Expected:** A thin vertical line (1px × 20px, `--border-default` color) separates the brand from tabs

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: A vertical separator element exists between the brand text and tab navigation in the app bar
- [ ] R2: Separator is 1px wide × 20px tall, colored `var(--border-default)`

## Acceptance Criteria

- [ ] AC 1: A separator element is visible between "Shipyard" and the first tab
- [ ] AC 2: Separator dimensions are 1px × 20px
- [ ] AC 3: Separator color is `var(--border-default)`
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `T6YLs` (name: "abSep") inside Header/AppBar, `width: 1, height: 20, fill: #30363d`
- Bug location: `internal/web/ui/index.html`, `<header class="app-bar">`

## Out of Scope

- Brand logo icon (separate spec SPEC-BUG-049)
- Tab icons (separate spec SPEC-BUG-047)

## Code Pointers

- `internal/web/ui/index.html` — `<header class="app-bar">` (lines 14–27)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
