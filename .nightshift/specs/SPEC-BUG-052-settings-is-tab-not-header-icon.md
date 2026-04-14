---
id: SPEC-BUG-052
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

# Settings is rendered as a nav tab instead of a gear icon in the header right group

## Problem

"Settings" appears as a text tab in the main navigation alongside Timeline, Tools, History, Servers, and Tokens. The UX-002 design shows Settings as a Lucide `settings` gear icon (18px, `--text-muted` color) in the header's right group — after the server count pill, not as a tab.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar component (`wnzNq`) right group (`a51KP`) contains node `mnhCj` — a Lucide "settings" icon_font, 18×18px, fill `#8b949e`. No "Settings" tab exists in the design's tab navigation.

## Reproduction

1. Open any page in Shipyard UI
2. Look at the header navigation tabs
3. **Actual:** "Settings" is the last tab in the nav bar (text, no icon)
4. **Expected:** "Settings" should not be a tab. Instead, a gear icon should appear in the header right group (after the server count pill)
5. Clicking the gear icon should navigate to the Settings view

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: "Settings" tab is removed from `<nav id="tab-nav">`
- [ ] R2: A Lucide `settings` gear icon (18px, `--text-muted`) appears in the header right group
- [ ] R3: Clicking the gear icon navigates to `#settings` view
- [ ] R4: Settings view continues to work correctly

## Acceptance Criteria

- [ ] AC 1: No "Settings" text tab appears in the tab navigation
- [ ] AC 2: A Lucide `settings` icon (18px) exists in the header right group, after the server count pill
- [ ] AC 3: Icon color is `var(--text-muted)` by default
- [ ] AC 4: Clicking the icon navigates to the Settings view
- [ ] AC 5: Settings view renders correctly
- [ ] AC 6: `go build ./...` passes
- [ ] AC 7: `go test ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `mnhCj` in Header/AppBar right group — `iconFontFamily: "lucide", iconFontName: "settings", width: 18, height: 18, fill: #8b949e`
- Design header tabs are: Timeline, Tools, History, Servers (4 tabs only)
- Bug location: `internal/web/ui/index.html`, `<nav id="tab-nav">` and header right group area

## Out of Scope

- Tokens tab presence (also not in design, but separate decision)
- Settings view content/layout
- Hover/active states for the gear icon

## Code Pointers

- `internal/web/ui/index.html` — `<nav id="tab-nav">` (lines 17–24) and header (lines 14–27)
- `internal/web/ui/index.html` — routing logic that handles `#settings`

## Gap Protocol

- Research-acceptable gaps: how the route switching works for non-tab navigation targets
- Stop-immediately gaps: if removing the tab breaks the routing system
- Max research subagents before stopping: 1
