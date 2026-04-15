---
id: SPEC-BUG-095
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

# Filter labels use text-secondary (#b1bac4), design specifies text-muted (#8b949e)

## Problem

The filter bar labels ("Server", "Method", "Direction") render in `color: rgb(177, 186, 196)` which is `#b1bac4` (`--text-secondary`). The UX-002 design specifies `fill: #8b949e` (`--text-muted`) for filter labels (`fServerLbl`, `fMethodLbl`, `fDirLbl`).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Filter labels `fontSize: 11`, `fontWeight: 500`, `fill: #8b949e` (text-muted).

## Reproduction

1. Open Timeline tab, inspect the "Server" or "Method" label above the filter dropdowns
2. **Actual:** color `rgb(177, 186, 196)` = `#b1bac4` (text-secondary)
3. **Expected:** color `#8b949e` (text-muted)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Filter labels use `color: var(--text-muted)` (#8b949e)

## Acceptance Criteria

- [ ] AC 1: "Server" label renders at #8b949e
- [ ] AC 2: "Method" label renders at #8b949e
- [ ] AC 3: "Direction" label renders at #8b949e
- [ ] AC 4: Labels are still readable against the dark background
- [ ] AC 5: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — `fServerLbl`, `fMethodLbl`, `fDirLbl` all use `fill: #8b949e`
- Live: labels use `--text-secondary` (#b1bac4) — lighter than intended

## Out of Scope

- Filter label font-size or font-weight (correct at 11px / 500)
- Filter dropdown styling (separate specs)

## Code Pointers

- `internal/web/ui/ds.css` — filter label rules (grep for `.filter-label` or similar)
- `internal/web/ui/index.html` — filter bar labels

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
