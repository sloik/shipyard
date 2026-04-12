---
id: SPEC-BUG-021
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

# Tool Browser response panel is capped at 400px instead of filling the available pane height

## Problem

The Tool Browser response viewer currently uses a hard `max-height:400px`,
which truncates the response area and leaves unused space in taller windows.

This drifts from the approved Pencil design:
- `Phase 1 — Tool Browser` frame: `d1yZ4`
- response section frame: `HqBpj`
- response body frame: `NdYmB`

In the design, both the response section and its body are `height:
"fill_container"`, which means the response panel is meant to expand and use
the remaining vertical space in the main pane rather than stop at a fixed 400px.

## Reproduction

1. Open the Tools tab
2. Select a tool with a visible response section
3. Resize the window taller or use a large display
4. **Actual:** the response JSON viewer remains capped at 400px height
5. **Expected:** the response section grows to fill the available remaining
   vertical space in the tool detail pane

## Root Cause

The frontend sets `max-height:400px; overflow:auto;` directly on
`#tool-response-json`, which overrides the fill-container intent of the design
and prevents the response area from participating in the main pane’s flexible
layout.

## Requirements

- [x] R1: The Tool Browser response panel must use remaining pane height rather
  than a fixed 400px cap.
- [x] R2: The response container hierarchy must preserve scrolling inside the
  response viewer, not on the whole page.
- [x] R3: The fix must respect the existing split between the header/meta area
  and the scrollable response body.

## Acceptance Criteria

- [x] AC 1: The response section grows vertically with the available space in
  the Tool Browser detail pane.
- [x] AC 2: The response JSON viewer remains internally scrollable for large
  payloads.
- [x] AC 3: No hard `max-height:400px` cap remains on the response viewer path.
- [x] AC 4: Regression tests cover the fill-height layout contract for the
  response section/viewer.
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
  - `HqBpj` (`response-section`)
  - `NdYmB` (`respBody`)

## Out of Scope

- Redesigning response header controls
- Changing JSON syntax rendering
- Adding new response modes beyond the current Text/JQ control

## Research Hints

- The detail pane already uses flex layout; the mismatch is likely in the
  response subtree’s sizing constraints rather than the overall page shell.
- Preserve `overflow:auto` semantics, but move them to the correct fill-height
  container.

## Gap Protocol

- Research-acceptable gaps:
  - exact element that should own `min-height:0` vs `overflow:auto`
- Stop-immediately gaps:
  - any change that removes scrolling entirely
  - any change that grows the whole page instead of the response panel
- Max research subagents before stopping: 0
