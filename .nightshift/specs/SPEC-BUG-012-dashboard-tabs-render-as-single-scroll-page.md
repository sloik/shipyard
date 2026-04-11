---
id: SPEC-BUG-012
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-006, SPEC-004, SPEC-017, SPEC-BUG-011]
prior_attempts: []
violates: [SPEC-006, SPEC-004, UX-002]
created: 2026-04-11
---

# Dashboard tabs do not isolate views; all content appears under Timeline and the tab bar scrolls away

## Problem

In the desktop app, the top navigation looks like a tab bar, but it does not behave
like one. Switching between Timeline, Tools, History, and Servers does not isolate
the active view. Instead, content from multiple sections appears to be rendered as
one long page under Timeline, and scrolling the page causes the top tabs to scroll
out of view.

This breaks the basic information architecture of the dashboard. A tabbed app
implies one active view at a time with persistent navigation. Rendering everything
into one scrolling document makes the dashboard confusing and makes the Servers
screen effectively undiscoverable even though the tab exists.

**Violated specs:**
- `SPEC-006` — Phase 0 UI Implementation
- `SPEC-004` — Phase 3: Multi-Server Management
- `UX-002` — Dashboard Design

**Violated criteria:**
- `SPEC-006 AC-1` — all 4 tabs are clickable and navigate to their view
- `SPEC-006 AC-2` — direct route access shows the requested view
- `SPEC-006 AC-4` — active tab updates on route change
- `SPEC-004 AC-2` — dashboard shows all servers in the server management view
- `UX-002 AC-10` — no visual element exists in the implementation that is not in the design

## Reproduction

1. Launch Shipyard desktop app with a config that has at least one server.
2. Wait for the web UI to load.
3. Click `Servers`, `History`, or `Tools` in the top navigation.
4. Scroll the page vertically.
5. **Actual:** the app behaves like one long document. Timeline content remains visible, other sections appear stacked into the same page, and the top navigation scrolls out of view.
6. **Expected:** only the selected route's view is visible at a time, and the top app bar remains persistent while the active view handles its own scrolling.

## Root Cause

The dashboard did not have a dedicated app-shell layout with a separate route
stack and scroll owner. The header, global banners, and all top-level views
were placed in the normal document flow, so the page could behave like one long
scrolling document in the desktop wrapper.

At the same time, top-level routing relied on ad hoc inline `style.display`
switching rather than an explicit route-view contract. That made the view
isolation fragile and hard to verify with tests.

## Requirements

- [ ] R1: Route navigation must show exactly one top-level dashboard view at a time.
- [ ] R2: Switching tabs must not leave previously active views visible in the page flow.
- [ ] R3: The app bar containing the top navigation must remain persistently visible while the active view scrolls.
- [ ] R4: The Servers tab must reveal the dedicated Servers view, not content embedded into the Timeline page.

## Acceptance Criteria

- [ ] AC 1: Clicking `Timeline`, `Tools`, `History`, and `Servers` shows only that route's top-level view; the other top-level views are hidden.
- [ ] AC 2: Direct hash navigation to `#/timeline`, `#/tools`, `#/history`, and `#/servers` opens the correct isolated view.
- [ ] AC 3: The visually active tab always matches the current route.
- [ ] AC 4: Scrolling within the dashboard does not move the top app bar out of view; the navigation remains accessible without scrolling back to the top of the full document.
- [ ] AC 5: The Servers route displays the dedicated server-management screen and its content is not appended below Timeline content.
- [ ] AC 6: `SPEC-006 AC-1`, `SPEC-006 AC-2`, `SPEC-006 AC-4`, and `SPEC-004 AC-2` now pass.
- [ ] AC 7: `internal/web/ui_layout_test.go` (or the equivalent web UI test file) contains regression coverage that asserts the top-level route/view contract: exactly one of `view-timeline`, `view-tools`, `view-history`, or `view-servers` is the active visible view for a given route.
- [ ] AC 8: The regression tests assert that the tab/navigation state follows the route state, including the active-tab class for `Timeline`, `Tools`, `History`, and `Servers`.
- [ ] AC 9: The regression tests assert that the app bar/top navigation is outside the per-view scrolling content region, so the layout contract does not collapse into one long scrolling page.
- [ ] AC 10: All existing tests pass after the fix.

## Context

- Routing and top-level view switching live in `internal/web/ui/index.html`.
- The app bar and top tabs are defined near the top of the file (`<header class="app-bar">`).
- Current route/view lookup is defined around the `views` map and `navigate(route)` function.
- Current initialization logic also patches routing for first-run and schema routes, so route overrides may be interacting with view visibility.
- Relevant areas to inspect:
  - `internal/web/ui/index.html` — top-level header, route map, `getRoute()`, `navigate()`, route patches, and top-level layout containers
  - `UX-002-dashboard-design.pen` — app bar and per-route screen layout
  - `SPEC-006-phase0-ui-implementation.md` — single-page hash routing contract
  - `SPEC-004-phase3-multi-server.md` — server-management view requirements

## Out of Scope

- Redesigning the navigation model
- Reworking copy or visual styling of the tabs
- Adding new routes or new dashboard features
- Changes to server-management behavior unrelated to route/view rendering

## Research Hints

- Confirm whether the bug is caused by incorrect `display` toggling, layout container structure, scroll ownership, or later route patches overriding the base navigation behavior.
- Verify whether the Wails desktop wrapper introduces a different viewport/height behavior than browser mode.
- Check for interactions between first-run routing (`navigate('servers')`), schema sub-routes, and the base `navigate()` function.
- Follow the repo's existing regression style first: `internal/web/ui_layout_test.go` currently uses structural assertions against embedded `index.html`, not screenshot snapshots.
- Relevant tags: `shipyard`, `dashboard`, `routing`, `wails`, `ui`
- DevKB to read before implementation: `DevKB/shell.md`, `DevKB/git.md`, and any repo-specific frontend guidance already in use for Shipyard.

## Gap Protocol

- Research-acceptable gaps: exact CSS/layout mechanism causing the scroll ownership issue; whether the regression is web-only or desktop-only
- Stop-immediately gaps: fix requires changing the intended navigation architecture or contradicts `UX-002`
- Max research subagents before stopping: 0
