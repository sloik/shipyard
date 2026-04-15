---
id: SPEC-BUG-058
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

# Filter Clear button missing Lucide x icon

## Problem

The "Clear" button in the Timeline filter bar is text-only (`<button class="btn btn-ghost">Clear</button>`). The UX-002 design shows a Lucide `x` icon (12px, `#8b949e`) before the "Clear" text, with `gap: 4`.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Filter bar node, Clear button (`Sg6A9`) contains icon_font node `ysHt1` — Lucide `x`, 12×12px, fill `#8b949e`, followed by text "Clear" (fontSize 11, fontWeight 500).

## Reproduction

1. Open the Timeline tab in Shipyard UI
2. Look at the filter bar, find the "Clear" button
3. **Actual:** Button shows only "Clear" text, no icon
4. **Expected:** Lucide `x` icon (12px) before "Clear" text

## Root Cause

(Agent fills in during run.)

## Requirements

- [x] R1: Clear button includes a Lucide `x` SVG icon (12px) before the "Clear" text
- [x] R2: Icon color is `var(--text-muted)`, matching the button text style

## Acceptance Criteria

- [x] AC 1: `#clear-filters-btn` contains a Lucide `x` SVG (12×12px, `stroke="currentColor"`) before the text "Clear"
- [x] AC 2: Button has `display:inline-flex; align-items:center; gap:4px` for icon+text layout
- [x] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `Sg6A9` (fClear) — children: `ysHt1` (Lucide x icon 12px, fill #8b949e) + `KAobF` (text "Clear", fontSize 11, fontWeight 500); gap 4, padding [6,10], cornerRadius 6
- Bug location: `internal/web/ui/index.html`, line ~117

## Out of Scope

- Clear button padding or border-radius changes
- Clear button hover/active states

## Code Pointers

- `internal/web/ui/index.html` — `<button class="btn btn-ghost" id="clear-filters-btn">` (line ~117)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
