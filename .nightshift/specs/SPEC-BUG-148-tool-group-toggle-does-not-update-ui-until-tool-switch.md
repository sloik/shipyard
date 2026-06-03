---
id: SPEC-BUG-148
template_version: 3
priority: 1
layer: 3
type: bugfix
status: blocked
after: [SPEC-BUG-145, SPEC-BUG-147]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Tools tab: clicking expand/collapse on a group does not update the UI until a different tool is selected

## Block Reason

Two consecutive background orchestrator runs (initial + one unblock pass) died to API stream idle timeout during investigation; no diagnosis, code, or report produced. Transient infra/API issue, not a spec defect. Re-run when background-agent streaming is stable, or run inline.


## Problem

On the Tools tab, clicking to expand or collapse a server group does not visibly
update the sidebar at the moment of the click. The group's tools do not
show/hide and the chevron does not change. The change only becomes visible after
the user selects a different tool, which re-renders the sidebar and then shows
the group in its toggled state.

Observed behavior:

- The user clicks a group header / chevron to collapse (or expand) a group.
- **Actual:** nothing visibly changes in the sidebar — the group's tools stay
  in their previous shown/hidden state and the chevron does not update.
- The user selects a different tool.
- The sidebar re-renders and the group now appears in the toggled (collapsed or
  expanded) state, confirming the toggle was registered but not reflected at
  click time.
- **Expected:** clicking the group header immediately toggles that group's
  visible collapsed/expanded state — its tools show/hide and the chevron
  updates — with no need to select a different tool.

## Reproduction

1. Open the Tools tab with at least one online server group that exposes tools.
2. Click the group header / chevron to collapse the group.
3. **Actual:** the group's tools remain visible and the chevron does not change.
4. Select any other tool in the sidebar.
5. The sidebar re-renders and the group now appears collapsed.
6. Repeat steps 2–5 expanding a collapsed group — same delayed behavior.

## Related specs / regression window

This behavior appeared after the recent Tool Browser group-collapse work. The
relevant recently-completed specs touching this exact code path, listed as the
likely regression origin (newest first):

- **SPEC-BUG-147** (done 2026-06-03) — persisted the per-server collapse state
  across reload/restart via local storage.
- **SPEC-BUG-145** (done 2026-06-03) — added user-driven group collapse
  interactivity (header-click toggle) and in-session retention across tool
  selection changes.
- **SPEC-BUG-018** (done; disposition corrected by SPEC-BUG-146) — historical
  context on group collapse behavior.

The immediate-on-click visual toggle is the behavior that regressed; the work in
one of SPEC-BUG-145 / SPEC-BUG-147 most likely introduced it. (This note marks
the regression window only — it is not a root-cause determination or a fix
direction.)

## Requirements

- [ ] R1: Clicking a group's header / chevron immediately toggles that group's
  visible collapsed/expanded state, with no tool selection change required.
- [ ] R2: On click, the group's tools immediately show (expand) or hide
  (collapse) to match the new state.
- [ ] R3: On click, the chevron immediately reflects the new state.
- [ ] R4: In-session retention across tool selection changes (SPEC-BUG-145) and
  persistence across reload/restart (SPEC-BUG-147) continue to work and are not
  regressed.
- [ ] R5: Existing offline/restarting auto-collapse behavior continues to work.

## Acceptance Criteria

- [ ] AC1: Clicking the header of an expanded group immediately hides its tools
  without selecting a different tool.
- [ ] AC2: Clicking the header of a collapsed group immediately shows its tools
  without selecting a different tool.
- [ ] AC3: The chevron immediately reflects the toggled state at click time.
- [ ] AC4: After an immediate toggle, selecting a different tool preserves the
  group's state (SPEC-BUG-145 behavior intact).
- [ ] AC5: After an immediate toggle, the group's state still persists across a
  reload (SPEC-BUG-147 behavior intact).
- [ ] AC6: A regression test covers that a group header click updates the
  group's rendered collapse state immediately (without requiring a re-render
  triggered by tool selection).
- [ ] AC7: `go test ./...` passes.
- [ ] AC8: `go vet ./...` passes.
- [ ] AC9: `go build ./...` passes.

## Context

The bug is in the Tools tab (Tool Browser) sidebar of the embedded web UI — the
group header click handling and how the toggled collapse state is reflected in
the rendered sidebar at click time.

## Out of Scope

- Any change to group visual styling, tool badges, or group contents beyond
  making the collapse/expand toggle update immediately on click.
- Changing which groups are collapsed by default on first render.
- Removing or weakening the SPEC-BUG-145 retention or SPEC-BUG-147 persistence
  behavior.

## Code Pointers

- `internal/web/ui/index.html` — Tool Browser sidebar render + the group-header
  click handler and the `userCollapsedGroups` store
- `internal/web/ui/ds.css` — group header / chevron / `.is-collapsed` styling
- `internal/web/ui_layout_test.go` — existing Tool Browser markup/JS tests
  (incl. `TestSPECBUG145_*`, `TestSPECBUG147_*`)

## Gap Protocol

- Research-acceptable gaps:
  - none anticipated.
- Stop-immediately gaps:
  - Any change that regresses SPEC-BUG-145 in-session retention or SPEC-BUG-147
    cross-reload persistence.
  - Any change that regresses offline/restarting auto-collapse.
- Max research subagents before stopping: 0
