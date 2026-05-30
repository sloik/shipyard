---
id: SPEC-BUG-144
template_version: 3
priority: 7
layer: 3
type: bugfix
status: in_progress
after: [SPEC-BUG-138, SPEC-BUG-141]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Traffic Resize, Pending, and Error Detail States Drift from UX-002

## Problem

The Traffic expanded detail panel has additional state-specific details in
UX-002 for resize handle, pending responses, and error responses. The current
implementation only partially follows these states.

Observed implementation drift:

- `.resize-handle::after` renders a 32x2 grip, while UX-002 uses a 40x3 grip
  inside an 8px-tall handle.
- Pending response detail uses the same generic response code header path and a
  generic spinner body instead of the UX-002 pending split structure.
- Error detail uses generic detail shell styling plus a response badge header,
  while UX-002 gives the error row/detail a danger accent and preserves the
  request/response panel structure.

UX-002 reference:

- `resize-handle` (`yETeS`): height `8`, full width, centered grip 40x3,
  grip fill `#30363d`, corner radius 2
- `State - Pending Row Expanded` (`TpnPZ`): pending row/detail with accent
  selection, request panel populated, response panel awaiting response
- `State - Error Row Expanded` (`c95tP`): error row/detail with danger accent
  while retaining split request/response panels

## Requirements

- [x] R1: Traffic detail resize handle must match UX-002 dimensions: 8px handle
  height, centered 40x3 grip, border-default fill, and no visual drift from the
  selected detail shell.
- [x] R2: Pending response details must use the same split-view panel chrome as
  completed details, with request populated and response clearly awaiting.
- [x] R3: Error response details must use danger accent on row/detail shell
  while preserving request/response split-view layout and response panel chrome.
- [x] R4: State-specific visual changes must not alter row matching, expand,
  collapse, copy, filter, or resize behavior.
- [x] R5: Tests must cover completed, pending, and error detail markup.

## Acceptance Criteria

- [x] AC 1: Traffic detail resize handle renders an 8px-tall hit area with a
  centered 40x3 grip.
- [x] AC 2: Pending detail state keeps request and response panels visible;
  response panel shows an awaiting state without losing the response header.
- [x] AC 3: Error detail state uses danger accent for row/detail shell and keeps
  the request/response panel structure intact.
- [x] AC 4: Copy and filter controls are present or intentionally disabled per
  panel state, and tests pin the intended behavior.
- [x] AC 5: Dragging the resize handle still changes detail height after the
  visual adjustment.
- [x] AC 6: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`
- Design nodes: `resize-handle` (`yETeS`), `State - Pending Row Expanded`
  (`TpnPZ`), `State - Error Row Expanded` (`c95tP`)
- Current implementation:
  - `internal/web/ui/index.html` - `renderDetailPanel`
  - `internal/web/ui/ds.css` - `.resize-handle`, `.detail-panel`,
    `.table-row.row-expanded`
- Related specs: `SPEC-006`, `SPEC-BUG-033`, `SPEC-041`

## Out of Scope

- Reworking the resize drag algorithm beyond preserving existing behavior.
- Changing backend matching of requests to responses.
- Changing Tool Browser resize handle.

## Code Pointers

- `internal/web/ui/index.html` - `renderDetailPanel`, expand/collapse handlers
- `internal/web/ui/ds.css` - Resize Handle and Detail Panel sections
- `internal/web/ui_layout_test.go` - UI source tests

## Gap Protocol

- Research-acceptable gaps:
  - Whether pending/error state classes should be applied to row, detail, or
    both.
  - Whether resize handle dimensions should be global or Traffic-scoped.
- Stop-immediately gaps:
  - Pending or error details no longer display one side of the split view.
  - Resize handle becomes non-draggable or too small to hit.
- Max research subagents before stopping: 1
