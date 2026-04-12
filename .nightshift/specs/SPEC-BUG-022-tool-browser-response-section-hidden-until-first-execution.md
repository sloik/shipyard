---
id: SPEC-BUG-022
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: [UX-002, SPEC-BUG-021]
violates: [UX-002]
prior_attempts: []
created: 2026-04-12
---

# Tool Browser response section stays hidden until the first execution

## Problem

The Tool Browser currently hides the entire response section when a tool is
selected and only reveals it after a successful or failed `tools/call`.

That drifts from the approved Pencil design for `Phase 1 — Tool Browser`:
- phase frame: `d1yZ4`
- response section: `HqBpj`
- response header: `Q9lu4`
- response body variants: `NdYmB`, `EhUVK`, `dE3d4`

In the design, the response area is part of the selected-tool detail layout,
with defined header/body states for idle, loading, success, and error. It is
not a missing region that appears only after the first execution.

## Reproduction

1. Open the Tools tab
2. Select any tool from the sidebar
3. Observe the detail pane before pressing `Execute`
4. **Actual:** the response section is not rendered at all
5. **Expected:** the response section remains visible in the detail pane, with
   an idle/empty response state until a tool call is made

## Root Cause

`selectTool()` explicitly hides `#tool-response-section` every time a tool is
selected:

- `internal/web/ui/index.html`

This makes the detail pane structurally diverge from the Phase 1 layout and
prevents the response region from serving as a stable pane-level affordance.

## Requirements

- [x] R1: Selecting a tool must keep the response section visible in the detail
  pane.
- [x] R2: The response section must show an explicit idle state before the
  first execution.
- [x] R3: Loading, success, and error states must continue to render within the
  same response region rather than replacing it.

## Acceptance Criteria

- [x] AC 1: After selecting a tool, the response header and body region are
  visible before execution.
- [x] AC 2: The pre-execution state uses a stable placeholder/idle presentation
  instead of removing the section from layout.
- [x] AC 3: Executing a tool transitions the existing response region into
  loading and then success/error without layout pop-in.
- [x] AC 4: Regression tests cover the selected-tool idle response state.
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
  - `Q9lu4` (`respHeader`)
  - `NdYmB` / `EhUVK` / `dE3d4` (`respBody` states)

## Out of Scope

- Redesigning the response header controls
- Adding new response analysis modes beyond the current Text/JQ split
- Changing backend execution behavior

## Research Hints

- Keep the response section mounted and swap only its body state.
- Reuse existing loading and error content rather than introducing a second
  response container.

## Nightshift Outcome

- Kept `#tool-response-section` mounted in the Tool Browser detail pane.
- Added an explicit idle placeholder before first execution.
- Moved loading into the existing response region instead of swapping to a
  separate external block.
- Added structural regression coverage in `internal/web/ui_layout_test.go`.

## Gap Protocol

- Research-acceptable gaps:
  - exact idle-state copy to use before first execution
- Stop-immediately gaps:
  - any fix that reintroduces layout pop-in by toggling the whole section
  - any change that removes loading or error feedback
- Max research subagents before stopping: 0
