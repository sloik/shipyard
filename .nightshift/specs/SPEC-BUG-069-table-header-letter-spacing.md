---
id: SPEC-BUG-069
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

# Table header has letter-spacing 0.05em not present in design

## Problem

The `.table-header > *` CSS rule includes `letter-spacing: 0.05em` (renders as 0.5px). The UX-002 design header-row text nodes do not specify any letter-spacing property, meaning it should be `normal`.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header-row node (`iwPKi`) text nodes have no letterSpacing property.

## Reproduction

1. Open the Timeline tab in Shipyard UI
2. Inspect any table header cell
3. **Actual:** letter-spacing is 0.5px (0.05em)
4. **Expected:** letter-spacing should be `normal` (no extra spacing)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Remove `letter-spacing: 0.05em` from `.table-header > *`

## Acceptance Criteria

- [ ] AC 1: `.table-header > *` in `ds.css` does NOT include `letter-spacing`
- [ ] AC 2: Table header text renders with normal letter-spacing
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, header-row text nodes — no letterSpacing property present
- Bug location: `internal/web/ui/ds.css`, `.table-header > *` (line ~1002)

## Out of Scope

- Table header font-size (SPEC-BUG-068)
- Table header color (SPEC-BUG-056)
- Table header text-transform (SPEC-BUG-064)

## Code Pointers

- `internal/web/ui/ds.css` — `.table-header > *` (line ~1002, `letter-spacing: 0.05em`)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
