---
id: SPEC-BUG-071
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

# Time column uses monospace font, design specifies Inter

## Problem

The time column cells use the `.timestamp` class which sets `font-family: var(--font-mono)` (JetBrains Mono). The UX-002 design specifies `fontFamily: "Inter"` for the time text node, matching the body font.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Data row time text node `RfT5o` (r1TimeLbl) has `fontFamily: "Inter", fontSize: 12`.

## Reproduction

1. Open the Timeline tab with traffic data
2. Inspect the time column text (e.g., "2s ago")
3. **Actual:** JetBrains Mono (monospace) font
4. **Expected:** Inter (sans-serif) font, matching the design

## Root Cause

`.timestamp` class in `ds.css` sets `font-family: var(--font-mono)` globally. Table row time cells (`data-col="time"`) and detail panel timestamps both use `.timestamp`, but only row cells should use Inter. Fix: scoped override `.timestamp[data-col="time"] { font-family: var(--font-sans); }` — targets only table row time cells (which have `data-col="time"`), leaves detail panel timestamps as monospace.

## Requirements

- [x] R1: Time column text uses `font-family: var(--font-sans)` (Inter), not monospace

## Acceptance Criteria

- [x] AC 1: Time cells in data rows use Inter (sans-serif) font, not JetBrains Mono
- [x] AC 2: `.timestamp` class (or time cell styling) no longer forces monospace for row time cells
- [x] AC 3: Time cells still render correctly (e.g., "2s ago", "1m ago")
- [x] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `RfT5o` (r1TimeLbl) — `fontFamily: "Inter", fontSize: 12`
- Bug location: `internal/web/ui/ds.css`, `.timestamp` class (line ~917) applies `font-family: var(--font-mono)`
- Note: The `.timestamp` class may be used elsewhere — ensure change is scoped to table row time cells

## Out of Scope

- Time format or content changes
- Method column font (already correct as monospace)
- Timestamp styling outside of data rows

## Code Pointers

- `internal/web/ui/ds.css` — `.timestamp` (line ~917)
- `internal/web/ui/index.html` — JS that creates time cells (search for `timestamp` class usage in row creation)

## Gap Protocol

- Research-acceptable gaps: whether `.timestamp` is used outside row cells and needs scoped override
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
