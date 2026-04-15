---
id: SPEC-BUG-057
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Row expand chevron uses Unicode triangle instead of Lucide chevron-down

## Problem

The row expand/collapse indicator uses a CSS `::before` pseudo-element with Unicode right-pointing triangle (`\25B6`) rotated on expand. The UX-002 design specifies a Lucide `chevron-down` icon at 14px, fill `#8b949e`, in the expand column.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Data row node (`sxbeT`), expand column (`Vtxjs`) contains icon_font node `yjqMq` — Lucide `chevron-down`, 14×14px, fill `#8b949e`.

## Reproduction

1. Open the Timeline tab with traffic data
2. Look at the rightmost column of any data row
3. **Actual:** Small Unicode triangle (▶) rendered via CSS `::before` pseudo-element
4. **Expected:** Lucide `chevron-down` SVG icon, 14px, `var(--text-muted)` color

## Root Cause

(Agent fills in during run.)

## Requirements

- [x] R1: Row chevron is a Lucide `chevron-down` SVG icon, not a Unicode triangle
- [x] R2: Icon is 14px, colored `var(--text-muted)`
- [x] R3: Expand/collapse rotation behavior is preserved (rotated state for expanded rows)

## Acceptance Criteria

- [x] AC 1: `.row-chevron` no longer uses `::before` with Unicode content
- [x] AC 2: Row chevron contains a Lucide `chevron-down` SVG (14×14px, `stroke="currentColor"`)
- [x] AC 3: Collapsed rows show the chevron pointing right (rotated -90deg or equivalent)
- [x] AC 4: Expanded rows show the chevron pointing down (0deg rotation)
- [x] AC 5: Transition animation is preserved
- [x] AC 6: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `yjqMq` inside row expand column `Vtxjs` — `iconFontFamily: "lucide", iconFontName: "chevron-down", width: 14, height: 14, fill: #8b949e`
- Bug location: `internal/web/ui/ds.css` `.row-chevron::before` (line ~1062) and JS that creates row HTML
- Note: Rows are created dynamically in JS. The chevron element is generated in the `createRow()` or equivalent function in the `<script>` section of `index.html`.

## Out of Scope

- Row expand content/detail panel
- Row hover or selection styling

## Code Pointers

- `internal/web/ui/ds.css` — `.row-chevron`, `.row-chevron::before` (lines ~1050–1069)
- `internal/web/ui/index.html` — JS function that creates table rows (search for `row-chevron`)

## Gap Protocol

- Research-acceptable gaps: how row HTML is generated in JS (grep for `row-chevron` in the script)
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
