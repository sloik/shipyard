---
id: SPEC-BUG-047
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-14
---

# Navigation tabs are text-only, missing Lucide icons

## Problem

Every tab in the app bar renders as plain text only. The UX-002 design shows each tab with a Lucide icon (14px) to the left of the label text. This is one of the most visually prominent differences between the live UI and the design, visible on every page.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar tab instances (`7cucN`, `k09Bz`, `RrVA7`, `qUXmt`) each contain an `icon_font` node with a specific Lucide icon.

## Reproduction

1. Open any page in Shipyard UI
2. Look at the tab navigation in the header
3. **Actual:** Tabs show only text labels (Timeline, Tools, History, Servers, Tokens, Settings)
4. **Expected:** Each tab should show a Lucide icon (14px) + text label with gap 6px. Design-specified icons:
   - Timeline: `activity`
   - Tools: `wrench`
   - History: `history`
   - Servers: `server`
   - (Tokens and Settings are not in the design header tabs)

## Root Cause

The `<nav id="tab-nav">` in `index.html` contained only text labels with no SVG icons. The `.tab` CSS class already had `display:inline-flex; align-items:center; gap:6px` in place — the icons simply were never added to the HTML. Fix: added inline Lucide SVGs with `stroke="currentColor"` directly in each tab anchor so color inherits from the parent element's `color` property, which is controlled by `.tab-active` / `.tab-default` CSS classes.

## Requirements

- [x] R1: Each tab in the header nav displays a Lucide icon to the left of the label text
- [x] R2: Icons are 14px, using the Lucide icon font already available in the codebase
- [x] R3: Icon color follows tab state: `--text-primary` for active, `--text-muted` for default
- [x] R4: Gap between icon and label is 6px (matching design)

## Acceptance Criteria

- [x] AC 1: Timeline tab has Lucide `activity` icon
- [x] AC 2: Tools tab has Lucide `wrench` icon
- [x] AC 3: History tab has Lucide `history` icon
- [x] AC 4: Servers tab has Lucide `server` icon
- [x] AC 5: Icons are 14×14px
- [x] AC 6: Active tab icon uses `var(--text-primary)` color
- [x] AC 7: Default tab icon uses `var(--text-muted)` color
- [x] AC 8: `go build ./...` passes
- [x] AC 9: `go vet ./...` passes

## Context

- Design reference: UX-002 Pencil file, nodes `7cucN` (Timeline/active), `k09Bz` (Tools), `RrVA7` (History), `qUXmt` (Servers)
- Tab/Active component: `ae085` — icon_font 14px + text, fontWeight 600
- Tab/Default component: `3wZYe` — icon_font 14px + text, fontWeight 500
- Bug location: `internal/web/ui/index.html`, `<nav id="tab-nav">` section

## Out of Scope

- Tokens and Settings tab icons (not defined in UX-002 design)
- Tab font-weight change (separate spec SPEC-BUG-053)
- Adding/removing tabs from the nav

## Code Pointers

- `internal/web/ui/index.html` — `<nav id="tab-nav">` (lines 17–24)
- `internal/web/ui/ds.css` — `.tab` rule

## Gap Protocol

- Research-acceptable gaps: how Lucide icons are loaded in the codebase (check existing server card icons for pattern)
- Stop-immediately gaps: if Lucide font is not available in the project
- Max research subagents before stopping: 1
