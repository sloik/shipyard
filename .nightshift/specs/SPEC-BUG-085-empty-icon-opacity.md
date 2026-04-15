---
id: SPEC-BUG-085
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: [SPEC-BUG-079, SPEC-BUG-080, SPEC-BUG-081]
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Empty state icon has opacity 0.5, design uses full opacity with muted color

## Problem

The `.empty-state .empty-icon` class applies `opacity: 0.5` to the icon. The UX-002 design does not use opacity on empty state icons — instead, icons have full opacity and use `stroke: var(--text-muted)` (#8b949e) for subdued appearance. Once Unicode emojis are replaced with Lucide SVGs (BUG-079/080/081), the 0.5 opacity will make them too faint.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Empty state icons in the design have full opacity, color controlled by stroke/fill, not opacity.

## Reproduction

1. Open any tab with an empty state (Timeline, History, or Servers with no data)
2. Inspect the empty-icon element
3. **Actual:** `opacity: 0.5` applied
4. **Expected:** Full opacity (`opacity: 1`), color handled by `color: var(--text-muted)` or SVG stroke

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Remove `opacity: 0.5` from `.empty-state .empty-icon`
- [ ] R2: Ensure icon color is `var(--text-muted)` via `color` property (for SVG currentColor inheritance)

## Acceptance Criteria

- [ ] AC 1: `.empty-state .empty-icon` does not have `opacity: 0.5`
- [ ] AC 2: Icon color is `var(--text-muted)` (#8b949e)
- [ ] AC 3: Icon is visible but appropriately subdued (not overly bright, not too faint)
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — empty state icons use stroke color, no opacity
- Live: `.empty-state .empty-icon { font-size: 32px; margin-bottom: 12px; opacity: 0.5; }`
- Bug location: `internal/web/ui/ds.css` — `.empty-state .empty-icon` (line ~1387)

## Out of Scope

- Replacing Unicode with Lucide SVGs (SPEC-BUG-079, 080, 081)
- Empty state text styles
- Empty state icon sizes (handled per-icon in BUG-079/080/081)

## Code Pointers

- `internal/web/ui/ds.css` — `.empty-state .empty-icon` (line ~1387)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
