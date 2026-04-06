---
id: SPEC-BUG-011
template_version: 2
priority: 1
layer: 2
type: bugfix
status: ready
after: [SPEC-017, SPEC-BUG-010]
prior_attempts: []
violates: "SPEC-017 R1 — desktop app should be usable on first launch"
created: 2026-04-06
---

# First-run UX: navigate to Servers view when 0 servers configured

## Problem

When a user double-clicks Shipyard.app for the first time, the app opens to the
Timeline view which shows "No traffic yet" with vague instructions about
configuring a client. The user has no idea what to do — there are no actionable
buttons, the sidebar is empty, and the onboarding steps don't mention auto-import.

The Servers view already has a good empty state with Auto-Import and Add Server
buttons, but the user never sees it because Timeline is the default.

Design: `UX-002-dashboard-design.pen` frame "Desktop — First Run (0 servers)"

## Requirements

- [ ] R1: When 0 servers are configured, the app defaults to the Servers view (not Timeline)
- [ ] R2: The "0 servers" badge in the header is clickable and navigates to Servers view
- [ ] R3: Timeline empty state includes a "Set Up Servers" link/button to navigate to Servers view

## Acceptance Criteria

- [ ] AC 1: On first launch (0 servers), hash route is `#/servers` and Servers tab is visually active
- [ ] AC 2: Servers empty state shows: server icon, "No servers configured" title, description mentioning auto-import, Auto-Import button (default style), Add Server button (primary style)
- [ ] AC 3: Clicking "0 servers" badge in header navigates to `#/servers`
- [ ] AC 4: Timeline empty state has a visible link to Servers view for users who navigate there manually
- [ ] AC 5: Once servers are added, subsequent launches default to Timeline as normal
- [ ] AC 6: All existing tests pass

## Context

- Design reference: `UX-002-dashboard-design.pen` → frame "Desktop — First Run (0 servers)" (id: `mmV80`)
- Routing is hash-based: `getRoute()` in `index.html` line 601 defaults to `'timeline'`
- Init happens at line 3256: `navigate(getRoute())`
- Servers empty state HTML is at line 488-494
- The existing Servers empty state already has an Auto-Import button (`servers-empty-import-btn`)
- The design shows two buttons: Auto-Import (default) + Add Server (primary) — the current HTML only has Auto-Import

## Out of Scope

- Welcome wizard or onboarding modal
- Persistent "first run" flag / localStorage tracking
- Changes to the Auto-Import modal flow itself
- System tray or startup preferences
