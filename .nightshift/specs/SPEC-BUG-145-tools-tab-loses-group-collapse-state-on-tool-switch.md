---
id: SPEC-BUG-145
template_version: 3
priority: 1
layer: 3
type: bugfix
status: in_progress
after: []
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Tools tab loses server-group collapse state when the selected tool changes

## Problem

On the Tools tab, the user can collapse (fold) individual server groups in the
sidebar. That collapsed state is not preserved when the selected tool changes:
selecting a different tool causes every server group to return to its expanded
(unfolded) state, discarding the folds the user just made.

Observed behavior:

- The user folds one or more server groups in the Tools sidebar.
- The user then selects a different tool (in any group).
- **Actual:** all server groups re-expand; the user's collapsed groups are
  unfolded again.
- **Expected:** groups the user collapsed stay collapsed when a different tool
  is selected; only groups the user explicitly toggles change their fold state.

This is observable any time the sidebar lists more than one collapsible server
group with at least one group folded.

## Reproduction

1. Open the Tools tab with at least two online servers that each expose tools.
2. Collapse one or more server groups by clicking their group header / chevron.
3. Confirm those groups are folded (chevron in collapsed state, tools hidden).
4. Select a different tool — either another tool in an expanded group, or a
   tool inside a still-expanded group.
5. **Actual:** the previously folded server groups are expanded again.
6. **Expected:** the previously folded server groups remain folded; the
   chevron state of each group is unchanged except for groups the user
   explicitly toggled.

## Requirements

- [ ] R1: When the selected tool changes, each server group retains the
  collapse/expand state the user last set for it.
- [ ] R2: Collapsing or expanding a group affects only that group; it must not
  reset the fold state of other groups.
- [ ] R3: The chevron orientation of each group continues to match that group's
  retained collapse state after a tool selection change.
- [ ] R4: Existing offline/restarting auto-collapse behavior continues to work
  and is not regressed by retaining user-set state for online groups.

## Acceptance Criteria

- [ ] AC 1: With two or more groups present and at least one group folded,
  selecting a different tool leaves the folded group(s) folded.
- [ ] AC 2: With a group expanded by the user, selecting a different tool leaves
  that group expanded.
- [ ] AC 3: Toggling one group's collapse state does not change any other
  group's collapse state.
- [ ] AC 4: Each group's chevron reflects its retained collapse state after a
  tool selection change.
- [ ] AC 5: A regression test in the Tool Browser markup/JS test suite covers
  collapse-state retention across a tool selection change.
- [ ] AC 6: `go test ./...` passes.
- [ ] AC 7: `go vet ./...` passes.
- [ ] AC 8: `go build ./...` passes.

## Context

The bug is in the Tools tab (Tool Browser) sidebar rendering and selection
behavior of the embedded web UI. Server-group collapse is already an
interactive feature in the live app (see the disposition note on SPEC-BUG-018,
which confirmed groups do collapse/expand); the defect is that the collapse
state is not retained when the selected tool changes and the sidebar re-renders.

UX reference: `.nightshift/specs/UX-002-dashboard-design.pen` — Phase 1 Tool
Browser frame and the `ToolList/Group` component with collapsed/expanded
chevron states.

## Out of Scope

- Persisting collapse state across a full Tools reload, app restart, or page
  reload (backend or storage-backed persistence). This spec covers retaining
  state within the live Tools session across tool selection changes only.
- Any change to group visual styling, tool badges, or group contents beyond
  preserving collapse state.
- Changing which groups are collapsed by default on first render.

## Code Pointers

- `internal/web/ui/index.html` — Tool Browser sidebar markup and selection JS
- `internal/web/ui/ds.css` — group header / chevron / `.is-collapsed` styling
- `internal/web/ui_layout_test.go` — existing Tool Browser markup/JS tests

## Gap Protocol

- Research-acceptable gaps:
  - Whether a group's default state on first render should be expanded or
    collapsed (only the *retention across tool switches* is in scope here).
- Stop-immediately gaps:
  - Any change that disables or removes group collapse interactivity instead of
    retaining its state.
  - Any change that regresses offline/restarting auto-collapse behavior.
  - Adding backend/storage persistence of collapse state (explicitly out of
    scope).
- Max research subagents before stopping: 0
