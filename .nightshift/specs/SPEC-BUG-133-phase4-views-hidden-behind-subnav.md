---
id: SPEC-BUG-133
template_version: 3
priority: 2
layer: 2
type: bugfix
status: in_progress
after: [UX-002, SPEC-006-001, SPEC-006-002, SPEC-006-003]
violates: [UX-002, SPEC-006-001, SPEC-006-002, SPEC-006-003]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Phase 4 Sessions, Profiling, and Schema Views Are Hidden Behind Subnavigation

## Problem

The current app bar exposes only `Traffic`, `Tools`, `History`, and `Servers`.
Phase 4 views are implemented, but they are hidden behind secondary routes:

- Sessions lives under History subnavigation.
- Performance/profiling lives under History subnavigation.
- Schema changes live under a Servers sub-view.

Existing UX-002-backed specs document the design navigation model as a top-level
dashboard tab set that includes `Traffic`, `Tools`, `History`, `Servers`,
`Sessions`, `Profiling`, and `Schema`. Hiding Phase 4 surfaces behind unrelated
tabs makes those features harder to discover and keeps the implementation out of
alignment with the design source of truth.

**Violated spec:** UX-002 (Dashboard Design)

**Violated criteria:** Dashboard navigation tabs should match the UX-002 tab
set. SPEC-BUG-099 captured this explicitly when removing the non-designed
Tokens top-level tab.

**Violated specs:** SPEC-006-001, SPEC-006-002, SPEC-006-003

**Violated criteria:** Each Phase 4 feature has a user-facing dashboard surface.
Those surfaces should be reachable through the designed navigation model rather
than buried under a different feature's subnav.

## Reproduction

1. Open the Shipyard dashboard.
2. Inspect the app bar.
3. **Actual:** top-level nav shows only `Traffic`, `Tools`, `History`, and
   `Servers`.
4. Navigate to History.
5. **Actual:** Sessions and Performance appear as secondary History tabs.
6. Navigate to Servers and then schema route.
7. **Actual:** Schema appears as a Servers sub-view.
8. **Expected:** Phase 4 views are represented according to the UX-002
   top-level dashboard navigation model.

## Root Cause

Leave blank for the implementation pass.

## Requirements

- [ ] R1: Align the top-level dashboard navigation with the UX-002 tab model for
  Phase 4 surfaces.
- [ ] R2: Sessions must be directly discoverable from the main dashboard
  navigation.
- [ ] R3: Profiling must be directly discoverable from the main dashboard
  navigation.
- [ ] R4: Schema changes must be directly discoverable from the main dashboard
  navigation.
- [ ] R5: Existing deep links and route aliases for the old nested locations
  must continue to work or redirect cleanly.
- [ ] R6: The top app bar must remain responsive and must not reintroduce tab
  wrapping or overflow regressions.
- [ ] R7: Tokens remains out of the top-level nav unless UX-002 is explicitly
  updated to include it.

## Acceptance Criteria

- [ ] AC 1: Main app navigation exposes Phase 4 surfaces according to UX-002:
  Sessions, Profiling, and Schema are not hidden only behind History/Servers
  subnavigation.
- [ ] AC 2: `#/sessions`, `#/profiling`, and `#/schema` or equivalent designed
  top-level routes render the existing feature views.
- [ ] AC 3: Existing nested links such as `#/servers/schema`, if still present
  externally, continue to work or redirect without a blank page.
- [ ] AC 4: The app bar does not wrap vertically at the dashboard's supported
  desktop width.
- [ ] AC 5: SPEC-BUG-109 tab-nav anti-regression coverage remains passing.
- [ ] AC 6: SPEC-BUG-099's "Tokens is not a top-level design tab" contract
  remains passing.
- [ ] AC 7: Regression tests cover tab presence, route activation, and route
  isolation for the Phase 4 views.
- [ ] AC 8: `go test ./...`, `go vet ./...`, and `go build ./...` pass.

## Context

- Existing implementation:
  - `internal/web/ui/index.html` top-level nav currently has Traffic, Tools,
    History, and Servers.
  - History subnav contains Requests, Sessions, and Performance.
  - Servers has a Schema sub-view at `#/servers/schema`.
- Design/spec reference:
  - `.nightshift/specs/UX-002-dashboard-design.md`
  - `.nightshift/specs/SPEC-BUG-099-tokens-tab-not-in-design.md`
  - `.nightshift/specs/SPEC-BUG-109-tab-nav-stacks-vertically.md`
  - `.nightshift/specs/SPEC-006-001-session-recording.md`
  - `.nightshift/specs/SPEC-006-002-latency-profiling.md`
  - `.nightshift/specs/SPEC-006-003-schema-change-detection.md`

## Out of Scope

- Redesigning the Phase 4 pages themselves
- Changing profiling calculations or schema-change detection behavior
- Reintroducing a top-level Tokens tab
- Mobile navigation design

## Code Pointers

- `internal/web/ui/index.html` - app bar, route targets, History subnav, Servers
  schema sub-view, route activation
- `internal/web/ui/ds.css` - app bar and tab layout
- `internal/web/ui_layout_test.go` - navigation and route isolation tests

## Gap Protocol

- Research-acceptable gaps:
  - Confirming exact tab names from the current Pencil design once Pencil MCP is
    connected
  - Deciding whether route names should be `profiling` or `performance`
- Stop-immediately gaps:
  - If current Pencil design intentionally changed Phase 4 views back into
    nested subviews; update or supersede this spec instead of implementing it
  - Any app-bar change that makes supported desktop widths wrap vertically
- Max research subagents before stopping: 1
