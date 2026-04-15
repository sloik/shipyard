---
id: SPEC-BUG-065
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

# Time column header missing sort indicator icon

## Problem

The Time column header in the table shows only the text "Time" with no sort direction indicator. The UX-002 design includes a Lucide `chevron-down` icon (10px, `#8b949e`) next to the "Time" label, indicating the default sort direction.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header-row node (`iwPKi`), Time column (`xp49p`) contains both text node `daZfq` ("Time") and icon_font node `9EnOm` — Lucide `chevron-down`, 10×10px, fill `#8b949e`, with gap 4 between them.

## Reproduction

1. Open the Timeline tab in Shipyard UI
2. Look at the "Time" column header
3. **Actual:** Only text "Time" (or "TIME" with uppercase transform), no sort icon
4. **Expected:** "Time" text followed by a small chevron-down icon (10px) indicating sort direction

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Time column header includes a Lucide `chevron-down` SVG icon (10px) after the label text
- [ ] R2: Icon color is `var(--text-muted)` (#8b949e)
- [ ] R3: Gap between label and icon is 4px

## Acceptance Criteria

- [ ] AC 1: Time column header in Timeline table contains a Lucide `chevron-down` SVG (10×10px)
- [ ] AC 2: Icon appears after the "Time" text with 4px gap
- [ ] AC 3: Icon color is `var(--text-muted)`
- [ ] AC 4: Sort icon does not appear on other column headers (only Time has it in the design)
- [ ] AC 5: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `9EnOm` (thTimeSort) inside `xp49p` (thTime) — `iconFontFamily: "lucide", iconFontName: "chevron-down", width: 10, height: 10, fill: #8b949e`; parent has `gap: 4`
- Bug location: `internal/web/ui/index.html`, Timeline table header (line ~123)
- Only the Time column has a sort icon in the design; other columns have text-only headers

## Out of Scope

- Sort functionality or sort state toggling
- Sort icons on other columns
- Column width changes

## Code Pointers

- `internal/web/ui/index.html` — `<span data-col="time">Time</span>` (line ~123)

## Gap Protocol

- Research-acceptable gaps: whether History table also needs the sort icon (check design)
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
