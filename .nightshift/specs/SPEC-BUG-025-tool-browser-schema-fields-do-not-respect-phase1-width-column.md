---
id: SPEC-BUG-025
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

# Tool Browser schema-driven form fields stretch full-width instead of using the approved Phase 1 field column widths

## Problem

The Tool Browser currently renders schema-driven form fields as full-width
blocks spanning the detail pane. The approved Pencil design uses constrained
field widths, with primary field columns rendered at explicit widths such as
`400`, `240`, `200`, and `160` depending on field type and arrangement.

Relevant design nodes:
- `Mh6pJ` (`form-section`)
- `YAHoB` (`formFields`)
- `mO03J` (`field1`)
- reusable field components such as `Field/Text`, `Field/Number`, `Field/Enum`

This is not just spacing polish. The design encodes the density and reading
rhythm of the form by constraining field widths rather than letting every field
fill the entire pane.

## Reproduction

1. Open the Tools tab
2. Select a tool with one or more input parameters
3. Compare the form layout to the Phase 1 design states
4. **Actual:** generated fields stretch across the available detail width
5. **Expected:** fields follow the constrained-width column treatment defined in
   the design

## Root Cause

The schema renderer emits generic `.field` wrappers into a flex-column form with
no field-width constraints:

- `internal/web/ui/index.html`
- `internal/web/ui/ds.css`

As a result, the browser naturally stretches field blocks to the full width of
their container, ignoring the explicit field widths encoded in the Pencil form
components.

## Requirements

- [x] R1: Schema-driven fields must adopt the Phase 1 constrained-width layout
  instead of always stretching to pane width.
- [x] R2: Single-field forms must align with the 400px field-column treatment
  shown in the design.
- [x] R3: Mixed field types must preserve their intended width classes where the
  design differentiates them.
- [x] R4: Existing schema rendering behavior and data collection must remain
  unchanged.

## Acceptance Criteria

- [x] AC 1: A simple text-field form renders with the constrained column width
  used by the design rather than full-width stretching.
- [x] AC 2: Field variants that differ in design width can be represented by
  the UI structure or style system.
- [x] AC 3: The form still works for boolean, enum, array, number, and text
  fields.
- [x] AC 4: Regression tests cover the width contract for generated fields.
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
  - `Mh6pJ`
  - `YAHoB`
  - `mO03J`

## Out of Scope

- Redesigning schema field semantics
- Introducing new field types
- Backend schema changes

## Research Hints

- The current renderer may need width classes keyed by field type rather than a
  single unconstrained `.field` block.
- The design shows both single-column and mixed-width form rows; preserve the
  existing dynamic rendering, but add layout semantics.

## Gap Protocol

- Research-acceptable gaps:
  - how much of the mixed-width row behavior should be implemented in this bug
    fix versus a later form-layout spec
- Stop-immediately gaps:
  - any change that breaks form submission or value collection
  - any implementation that hardcodes one field width for every type without
    reflecting the design's differentiated layout
- Max research subagents before stopping: 0
