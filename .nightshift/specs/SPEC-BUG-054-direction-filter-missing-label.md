---
id: SPEC-BUG-054
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

# Timeline filter bar missing "Direction" label above the direction toggle

## Problem

The Timeline filter bar shows "Server" and "Method" labels above their respective dropdowns, but the direction seg-toggle (All / REQ → / ← RES) has no label. The UX-002 design shows a "Direction" label (`fontSize: 11, fontWeight: 500, color: #8b949e`) above the direction toggle, consistent with the other filter groups.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Phase 0 Traffic Timeline frame (`rRx2E`), Filter Bar node (`Ikqcl`), direction filter group (`ZaUry`) contains a text node (`7Awgc`, name: "fDirLbl") with content "Direction".

## Reproduction

1. Open the Timeline tab in Shipyard UI
2. Look at the filter bar below the header
3. **Actual:** Server has a "Server" label, Method has a "Method" label, but the direction toggle has no label
4. **Expected:** A "Direction" label should appear above the All/REQ→/←RES toggle

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: A "Direction" label appears above the direction seg-toggle in the filter bar
- [ ] R2: Label styling matches the other filter labels (font-size `--font-size-sm`, font-weight 500, color `--text-muted`)

## Acceptance Criteria

- [ ] AC 1: "Direction" label text is visible above the direction toggle
- [ ] AC 2: Label uses the same `.input-label` class (or equivalent styling) as "Server" and "Method" labels
- [ ] AC 3: The direction filter group is wrapped in an `.input-group` container (matching Server and Method groups)
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `7Awgc` inside filter group `ZaUry` — `content: "Direction", fontSize: 11, fontWeight: 500, color: #8b949e`
- Bug location: `internal/web/ui/index.html`, filter bar section (lines 103–107)

## Out of Scope

- Filter bar height or padding changes
- Direction toggle button styling
- Clear button styling

## Code Pointers

- `internal/web/ui/index.html` — `<div class="seg-toggle" id="dir-toggle">` (line ~103)
- `internal/web/ui/ds.css` — `.input-group`, `.input-label` rules

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
