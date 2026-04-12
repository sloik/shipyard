---
id: SPEC-BUG-028
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: [UX-002, SPEC-BUG-025]
violates: [UX-002]
prior_attempts: []
created: 2026-04-12
---

# Tool Browser long schema forms can overflow the detail pane without a usable scroll path

## Problem

In the Tool Browser, selecting a tool with a long schema-driven form can push
part of the detail pane out of view. For example, `lmstudio -> lms_load_model`
does not fit in the viewport, and the user cannot scroll the form area to reach
the hidden controls.

This violates the Tool Browser detail-pane contract in the approved Phase 1
design:
- `d1yZ4` (`Phase 1 — Tool Browser`)
- `ncART` (`main-content`)
- `Mh6pJ` (`form-section`)
- `HqBpj` (`response-section`)

The detail pane is intended to remain usable within the available viewport
height even when a selected tool has many parameters.

## Reproduction

1. Open the Tools tab
2. Select `lmstudio -> lms_load_model`
3. Observe the tool detail pane on a normal desktop window
4. **Actual:** lower form controls overflow below the visible pane and are not
   reachable via a usable scroll path
5. **Expected:** the detail pane or the form region scrolls so all controls
   remain reachable

## Root Cause

The Tool Browser detail pane currently combines:
- `#tools-main` with outer `overflow-y:auto`
- `#tool-detail` as a full-height flex column
- a large schema form section plus a persistent response section

But there is no explicit, well-owned vertical scrolling contract for long form
content inside the detail pane. With a sufficiently large schema, the flex
layout can trap content below the fold instead of allowing the form region to
scroll.

## Requirements

- [x] R1: Long schema-driven forms must remain fully reachable inside the Tool
  Browser detail pane.
- [x] R2: The fix must preserve the existing response-section layout introduced
  by `SPEC-BUG-021` and `SPEC-BUG-022`.
- [x] R3: Scrolling ownership must be explicit so the form and response regions
  do not fight each other.

## Acceptance Criteria

- [x] AC 1: A long form such as `lms_load_model` can be scrolled to reach all
  fields and actions.
- [x] AC 2: The response section remains usable after the scroll fix.
- [x] AC 3: No controls become unreachable due to overflow clipping.
- [x] AC 4: Regression tests cover the long-form scrolling contract in the Tool
  Browser detail pane.
- [x] AC 5: `go test ./...` passes.
- [x] AC 6: `go vet ./...` passes.
- [x] AC 7: `go build ./...` passes.

## Context

- Relevant implementation:
  - `internal/web/ui/index.html`
  - `internal/web/ui/ds.css`
  - `internal/web/ui_layout_test.go`
- Relevant live repro:
  - `lmstudio -> lms_load_model`
- Relevant design:
  - `.nightshift/specs/UX-002-dashboard-design.pen`
  - `d1yZ4`
  - `ncART`
  - `Mh6pJ`
  - `HqBpj`

## Out of Scope

- Redesigning the Tool Browser information architecture
- Changing schema field generation semantics
- Backend changes to LM Studio or tool schemas

## Research Hints

- The likely fix is in scroll ownership and flex sizing, not in schema data.
- Be careful not to regress the response-pane fill-height behavior already fixed
  in `SPEC-BUG-021`.

## Gap Protocol

- Research-acceptable gaps:
  - whether the scroll owner should be `#tool-detail`, the form section, or a
    dedicated inner wrapper
- Stop-immediately gaps:
  - any change that breaks access to the response section
  - any implementation that only works for one specific tool schema
- Max research subagents before stopping: 0
