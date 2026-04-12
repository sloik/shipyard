---
id: SPEC-BUG-027
template_version: 2
priority: 2
layer: 2
type: bugfix
status: ready
after: [UX-002, SPEC-004]
violates: [UX-002]
prior_attempts: []
created: 2026-04-12
---

# Servers view restarting state is rendered as a generic card footer badge instead of the approved restarting card

## Problem

In the Servers view, a restarting server currently renders inside the generic
server card with a footer badge that says `Restarting...`.

The approved Pencil design defines a dedicated restarting card state:
- card state: `qFcnB` (`State — Server Restarting Card`)
- top-right restarting pill: `72XWK`
- centered waiting body: `xdMRZ`

This is a distinct card composition with its own border treatment and centered
loading body, not just a generic card plus footer text.

## Reproduction

1. Open the Servers view
2. Put any managed server into `restarting` state
3. Observe the rendered card
4. **Actual:** the server card remains generic and only shows a footer badge
   `Restarting...`
5. **Expected:** the server renders with the dedicated restarting-state card
   treatment from the design

## Root Cause

The card renderer special-cases `restarting` only inside the action row:

- `internal/web/ui/index.html`
- `internal/web/ui/ds.css`

There is no separate markup or styling path for the design's restarting card
header pill, warning border, or centered waiting body.

## Requirements

- [ ] R1: Restarting servers must render with a dedicated restarting card state,
  not the generic server card body.
- [ ] R2: The card must include the warning pill/header treatment and centered
  loading body defined by the design.
- [ ] R3: Other server states (`online`, `crashed`, `stopped`) must keep their
  existing state-specific treatment.

## Acceptance Criteria

- [ ] AC 1: A restarting server card renders a state-specific header pill rather
  than only a footer badge.
- [ ] AC 2: The restarting card includes a centered waiting/loading body region.
- [ ] AC 3: The restarting state uses the design's warning border/tone rather
  than the default card border.
- [ ] AC 4: Regression tests cover restarting-card rendering.
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
  - `qFcnB`
  - `72XWK`
  - `xdMRZ`

## Out of Scope

- Changing restart lifecycle behavior
- Backend polling cadence
- Redesigning all server cards

## Research Hints

- This likely needs a restarting-specific branch in `renderServerCards()`, not
  just a CSS modifier on the existing footer action row.
- Preserve the current server identity and metadata, but restructure the state
  presentation to match the design.

## Gap Protocol

- Research-acceptable gaps:
  - whether restart-count metadata should remain visible in restarting state
- Stop-immediately gaps:
  - any fix that removes restart controls for non-restarting states
  - any implementation that treats restarting as only a badge-color change
- Max research subagents before stopping: 0
