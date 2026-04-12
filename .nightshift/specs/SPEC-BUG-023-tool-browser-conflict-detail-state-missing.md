---
id: SPEC-BUG-023
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: [UX-002, SPEC-BUG-017, SPEC-020]
violates: [UX-002]
prior_attempts: []
created: 2026-04-12
---

# Tool Browser does not render the conflicted-tool detail state from the approved design

## Problem

Shipyard already detects tool-name conflicts and surfaces them in the sidebar,
but the selected-tool detail pane does not render the conflict state defined in
the Phase 1 Pencil spec.

Approved design evidence:
- sidebar conflict banner: `x0et6`
- conflicted row component: `1P50f`
- main-pane conflict alert: `Kng5M`
- per-server implementation cards: `2cKIw`

Current implementation only shows the sidebar warning banner and inline
`also in: ...` labels. Selecting a conflicted tool renders the normal tool
detail pane with no conflict alert and no per-server comparison cards.

## Reproduction

1. Configure two servers that expose the same tool name
2. Open the Tools tab
3. Select one of the conflicting tools from the sidebar
4. **Actual:** the main pane shows the normal tool detail only
5. **Expected:** the main pane includes the approved conflict alert and the
   per-server implementation context from the Phase 1 design

## Root Cause

Conflict data is fetched into `toolConflicts`, but that state is only consumed
by the sidebar renderer. The selected-tool detail path does not branch on
conflict state and has no markup for the design's conflict alert or
implementation comparison cards.

## Requirements

- [x] R1: Selecting a conflicted tool must render a visible conflict alert in
  the main detail pane.
- [x] R2: The detail pane must show which servers provide that tool so the user
  can understand the collision before executing.
- [x] R3: The detail state must remain aligned with the approved Phase 1 visual
  language for conflicted tools.

## Acceptance Criteria

- [x] AC 1: A conflicted tool selection shows a conflict alert in the main pane.
- [x] AC 2: The alert identifies the selected tool name and explains the
  ambiguity.
- [x] AC 3: The detail pane includes the server-specific implementation
  breakdown or equivalent comparison structure called for by the design.
- [x] AC 4: Non-conflicted tools continue to show the standard detail layout.
- [x] AC 5: Regression tests cover conflicted-tool detail rendering.
- [x] AC 6: `go test ./...` passes.
- [x] AC 7: `go vet ./...` passes.
- [x] AC 8: `go build ./...` passes.

## Context

- Relevant implementation:
  - `internal/web/ui/index.html`
  - `internal/web/ui/ds.css`
  - `internal/web/ui_layout_test.go`
- Relevant design:
  - `.nightshift/specs/UX-002-dashboard-design.pen`
  - `x0et6` (`conflictBanner`)
  - `1P50f` (`ToolList/ItemConflict`)
  - `Kng5M` (`conflict-alert`)
  - `2cKIw` (`cards`)

## Out of Scope

- Changing backend conflict detection rules
- Resolving tool conflicts automatically
- Introducing execution-time conflict routing policy changes

## Research Hints

- The backend already exposes enough information to know when a tool is
  conflicted; the gap is the missing detail-pane presentation.
- Reuse the current selected-tool flow, but add a conflict branch before the
  standard detail rendering.

## Gap Protocol

- Research-acceptable gaps:
  - exact amount of schema detail to show inside each per-server card
- Stop-immediately gaps:
  - any fix that depends on changing backend conflict semantics
  - any implementation that only adds more sidebar warnings without a main-pane
    conflict state
- Max research subagents before stopping: 0
