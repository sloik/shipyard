---
id: SPEC-BUG-066
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Header elements all packed left — right-side group not pushed to far right

## Problem

All header children (logo, brand, separator, tabs, ws-indicator, server-count, settings) are flat flex children with `gap: 16px` and no grouping. They all pack to the left, leaving ~1246px of empty space on the right side of a 2001px header. The UX-002 design uses `justifyContent: space_between` with a left group (logo + brand + separator + tabs) and a right group (ws-indicator + server-count + settings icon), placing them at opposite edges.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar (`wnzNq`) has `justifyContent: "space_between"` with left group (`XasMC`, gap 12) and right group (`a51KP`, gap 12). Live header has `justify-content: normal` with all 7 elements as flat siblings.

## Reproduction

1. Open any page in Shipyard UI
2. Look at the header bar
3. **Actual:** Logo, brand, separator, tabs, live indicator, server count, settings button all clustered on the left; ~60% of header is empty space on the right
4. **Expected:** Logo+brand+separator+tabs on left, live indicator+server count+settings on far right

## Root Cause

All header children were flat flex siblings in `.app-bar` (which had `gap: 16px` but no `justify-content`). The fix adds `justify-content: space-between` to `.app-bar` (removing the flat `gap`), and wraps left elements (logo, brand, separator, tab-nav) in a `<div style="display:flex;align-items:center;gap:12px;">` and right elements (ws-indicator, server-count, settings-btn) in a second such div.

## Requirements

- [x] R1: Header right-side elements (ws-indicator, server-count, settings-btn) are pushed to the right edge of the header
- [x] R2: Left-side elements (logo, brand, separator, tab-nav) remain on the left
- [x] R3: Left group internal gap is 12px, right group internal gap is 12px

## Acceptance Criteria

- [x] AC 1: Settings button is positioned near the right edge of the header (within 16px padding)
- [x] AC 2: WS indicator, server count, and settings are grouped together on the right
- [x] AC 3: Logo, brand, separator, and tabs remain grouped on the left
- [x] AC 4: Gap between items within each group is 12px (matching design)
- [x] AC 5: Visual appearance matches header layout in UX-002 design
- [x] AC 6: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `wnzNq` (Header/AppBar) — `justifyContent: "space_between"`; left group `XasMC` (gap 12, children: logo+brand+separator+tabs); right group `a51KP` (gap 12, children: ws-indicator+server-count+settings)
- Bug location: `internal/web/ui/index.html`, `<header class="app-bar">` (lines 13–31)
- Implementation options: (a) wrap left/right elements in `<div>` groups, or (b) add `margin-left: auto` to ws-indicator, or (c) add a flex-grow spacer between tab-nav and ws-indicator

## Out of Scope

- Tab icon changes
- WS indicator styling (color, font)
- Settings button icon or size

## Code Pointers

- `internal/web/ui/index.html` — `<header class="app-bar">` (lines 13–31)
- `internal/web/ui/ds.css` — `.app-bar` (line ~751)

## Gap Protocol

- Research-acceptable gaps: best approach for left/right grouping without breaking existing JS
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
