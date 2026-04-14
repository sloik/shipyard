---
id: SPEC-BUG-018
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: [UX-002, SPEC-BUG-017]
violates: [UX-002]
prior_attempts: []
created: 2026-04-12
---

# Tool Browser groups are not collapsible despite the Phase 1 design showing expandable server groups

## Disposition

Invalidated on 2026-04-12 after live user verification. The reported runtime
behavior is that `lmstudio` groups do expand/collapse by clicking the chevron
or server row, so this spec should not be used as a fix target. Static code
inspection was insufficient evidence for a real bug here.

## Problem

The current Tool Browser sidebar renders server groups with a chevron and group
header styling, but online groups cannot actually be collapsed or expanded by
the user.

This is a spec drift against the approved Pencil design:
- `Phase 1 — Tool Browser` frame: `d1yZ4`
- reusable component: `ToolList/Group` (`0c5qR`)
- chevron icon in the group header: `tGIrC`
- explicit chevron components also exist in the design system:
  - `YitzQ` (`Chevron/Collapsed`)
  - `FO46h` (`Chevron/Expanded`)

The design language and component structure clearly indicate interactive
expand/collapse behavior for tool groups, not a static always-open list.

## Reproduction

1. Open the Tools tab with at least one online server that exposes tools
2. Observe the server group row includes a chevron and grouped tool list
3. Click the group header
4. **Actual:** nothing happens for online groups
5. **Expected:** the group toggles between collapsed and expanded, with the
   chevron state updating to match

## Root Cause

The frontend only applies `.is-collapsed` automatically for offline or
restarting groups during render, but there is no interactive click handler for
`.tool-group-header` and no persisted/ephemeral UI state that tracks collapsed
server groups. The only Tools sidebar click handler targets `.tool-item`.

## Requirements

- [ ] R1: Tool Browser groups must support user-driven expand/collapse behavior
  for online servers, not only offline/restarting auto-collapse.
- [ ] R2: The UI must maintain explicit collapsed state per server group.
- [ ] R3: Clicking the group header must toggle the collapsed state.
- [ ] R4: The chevron orientation must reflect the current collapsed state.
- [ ] R5: Existing offline/restarting behavior must continue to work.

## Acceptance Criteria

- [ ] AC 1: Clicking an online server group header in the Tools sidebar toggles
  the visibility of that group’s tools.
- [ ] AC 2: The chevron visually changes between expanded and collapsed states.
- [ ] AC 3: Offline/restarting groups still default to collapsed without
  breaking manual collapse behavior for normal groups.
- [ ] AC 4: Regression tests cover the presence of a group-header toggle path
  and collapsed-state handling in the Tool Browser markup/JS.
- [ ] AC 5: `go test ./...` passes.
- [ ] AC 6: `go vet ./...` passes.
- [ ] AC 7: `go build ./...` passes.

## Context

- Relevant implementation:
  - `internal/web/ui/index.html`
  - `internal/web/ui/ds.css`
  - `internal/web/ui_layout_test.go`
- Relevant design:
  - `.nightshift/specs/UX-002-dashboard-design.pen`
  - `0c5qR` (`ToolList/Group`)
  - `YitzQ` / `FO46h` chevron state components

## Out of Scope

- Changing Tool Browser visual style beyond collapse behavior
- Introducing backend persistence for collapsed UI state
- Redesigning group contents or tool badges

## Research Hints

- The current renderer already emits `.tool-group-header` and `.tool-group-chevron`
  plus `.is-collapsed`; the missing piece is interactive state management.
- Keep this a UI-state fix unless a concrete requirement for persistence
  appears.

## Gap Protocol

- Research-acceptable gaps:
  - whether collapsed state should reset on each Tools reload
- Stop-immediately gaps:
  - any “fix” that removes the chevron instead of implementing the behavior
  - any change that only collapses offline groups and leaves online groups
    non-interactive
- Max research subagents before stopping: 0
