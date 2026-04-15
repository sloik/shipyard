---
id: SPEC-BUG-105
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

# Header separator between brand and tabs is missing

## Problem

The UX-002 design has a vertical 1px separator line between the brand name ("Shipyard") and the nav tabs. The live UI has no separator — the brand name runs directly into the tab bar with no visual divider.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header left area should contain a 1×20px vertical separator between brand and tabs (design node `T6YLs`).

## Reproduction

1. Open any page, look at the header left area between "Shipyard" brand and the first tab
2. **Actual:** No separator; brand and tabs are adjacent
3. **Expected:** 1px-wide, 20px-tall vertical line using `$border-default` color

## Root Cause

BUG-048 already added the separator (`<span style="width:1px; height:20px; background:var(--border-default); flex-shrink:0;"></span>`) between the brand `<strong>` and `<nav id="tab-nav">` in `index.html` line 18. No code change required.

## Requirements

- [ ] R1: Add a vertical separator element between the brand name and the tab nav
- [ ] R2: Separator uses `border-default` color, 1px wide, ~20px tall

## Acceptance Criteria

- [ ] AC 1: A vertical separator is visible between brand and first tab
- [ ] AC 2: Separator color matches `var(--border-default)`
- [ ] AC 3: Separator height is approximately 20px
- [ ] AC 4: `go build ./...` passes

## Context

- Design: node `T6YLs` inside header left area (`XasMC`): `fill: $border-default`, `height: 20`, `width: 1`
- Live: no separator element exists in the header
- This is a purely additive fix — add an element, no existing elements change

## Out of Scope

- Brand name styling
- Tab styling (SPEC-BUG-104, SPEC-BUG-106, SPEC-BUG-107)

## Code Pointers

- `internal/web/ui/index.html` — header area, between brand and `<nav>` tabs
- `internal/web/ui/ds.css` — may need a `.separator` or `.divider` class

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
