---
id: SPEC-BUG-059
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

# Search bars use Unicode magnifying glass emoji instead of Lucide search SVG

## Problem

The search bars in the Tools sidebar and History filter bar use a Unicode magnifying glass emoji (`&#128269;` / 🔍) as the search icon. The UX-002 design specifies a Lucide `search` icon at 14px, fill `#8b949e`.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tool sidebar search node (`3Omh4`) contains icon_font node `1AmcV` — Lucide `search`, 14×14px, fill `#8b949e`. The current implementation uses a Unicode emoji character instead.

## Reproduction

1. Open the Tools tab in Shipyard UI
2. Look at the search bar in the sidebar
3. **Actual:** Unicode 🔍 emoji as search icon
4. **Expected:** Lucide `search` SVG icon, 14px, `var(--text-muted)` color
5. Same issue exists in the History tab search bar

## Root Cause

Both `<span class="search-icon">&#128269;</span>` elements in `internal/web/ui/index.html` (lines ~154 and ~292) used the Unicode code point for the 🔍 emoji instead of the Lucide SVG. The `.search-bar .search-icon` CSS rule already set `color: var(--text-muted)` — so only the HTML markup needed updating.

## Requirements

- [x] R1: Tool sidebar search icon is a Lucide `search` SVG (14px), not Unicode emoji
- [x] R2: History search bar icon is a Lucide `search` SVG (14px), not Unicode emoji
- [x] R3: Icon color is `var(--text-muted)`

## Acceptance Criteria

- [x] AC 1: `#tool-search-bar .search-icon` contains a Lucide `search` SVG (14×14px, `stroke="currentColor"`)
- [x] AC 2: `#history-search-bar .search-icon` contains a Lucide `search` SVG (14×14px, `stroke="currentColor"`)
- [x] AC 3: No Unicode `&#128269;` characters remain in search bar icons
- [x] AC 4: Icon color inherits `var(--text-muted)` from `.search-icon` class
- [x] AC 5: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `1AmcV` (sbSearchIcon) — `iconFontFamily: "lucide", iconFontName: "search", width: 14, height: 14, fill: #8b949e`
- Bug locations: `internal/web/ui/index.html`, lines ~154 and ~290
- Both instances use `<span class="search-icon">&#128269;</span>`

## Out of Scope

- Search bar input styling
- Search clear button styling
- History search result count badge

## Code Pointers

- `internal/web/ui/index.html` — `<span class="search-icon">&#128269;</span>` (lines ~154 and ~290)
- `internal/web/ui/ds.css` — `.search-bar .search-icon` (line ~540)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
