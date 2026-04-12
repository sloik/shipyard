---
id: SPEC-BUG-024
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: [UX-002, SPEC-BUG-017]
violates: [UX-002]
prior_attempts: []
created: 2026-04-12
---

# Tool Browser sidebar search uses a rounded input card instead of the approved Phase 1 search strip

## Problem

The Tool Browser sidebar search area is currently rendered as a boxed search
control with rounded corners and a full border. The approved Pencil design uses
an integrated full-width search strip at the top of the sidebar with only a
bottom divider.

Relevant design nodes:
- `3Omh4` (`search`)
- `1yePK` (`search`)

In the design, the sidebar search row is part of the sidebar chrome itself:
- width: `fill_container`
- padding: `[10,12]`
- bottom stroke only: `#21262d`
- no outer card border or inset pill treatment

## Reproduction

1. Open the Tools tab
2. Look at the search control at the top of the left sidebar
3. **Actual:** it renders as a rounded bordered search card inside an outer
   padded wrapper
4. **Expected:** it renders as the flush Phase 1 search strip with only the
   bottom divider treatment

## Root Cause

The sidebar reuses the generic `.search-bar` component and wraps it in an extra
`padding:8px` container:

- `internal/web/ui/index.html`
- `internal/web/ui/ds.css`

That shared component applies:
- background fill
- full border
- rounded corners

which conflicts with the Tool Browser-specific sidebar search treatment encoded
in the Pencil design.

## Requirements

- [x] R1: The Tool Browser sidebar search must use the Phase 1 strip treatment,
  not the generic rounded search card.
- [x] R2: The search row must remain full-width within the 260px sidebar and use
  the design's top-of-sidebar composition.
- [x] R3: Existing search behavior and clear-button interaction must remain
  unchanged.

## Acceptance Criteria

- [x] AC 1: The Tool Browser sidebar search no longer renders with the generic
  full border + rounded card chrome.
- [x] AC 2: The search row visually matches the design's full-width strip with
  bottom divider treatment.
- [x] AC 3: Search input, icon, and clear affordance still function.
- [x] AC 4: Regression tests cover the Tool Browser search row structure or
  class contract.
- [x] AC 5: `go test ./...` passes.
- [x] AC 6: `go vet ./...` passes.
- [x] AC 7: `go build ./...` passes.

## Context

- Relevant implementation:
  - `internal/web/ui/index.html`
  - `internal/web/ui/ds.css`
  - `internal/web/ui_layout_test.go`
- Relevant design:
  - `.nightshift/specs/UX-002-dashboard-design.pen`
  - `3Omh4`
  - `1yePK`

## Out of Scope

- Changing search/filter semantics
- Reworking the generic `.search-bar` component across the whole app
- Altering tool list grouping behavior

## Research Hints

- This likely needs a Tool Browser-specific variant rather than changing every
  existing `.search-bar` usage.
- Preserve the current search JS hooks while swapping the chrome structure.

## Gap Protocol

- Research-acceptable gaps:
  - whether to implement via a dedicated class or a Tool Browser-specific
    wrapper override
- Stop-immediately gaps:
  - any fix that breaks the current search input bindings
  - any change that globally regresses other search bars
- Max research subagents before stopping: 0
