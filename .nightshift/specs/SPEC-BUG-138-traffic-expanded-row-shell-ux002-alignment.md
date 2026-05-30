---
id: SPEC-BUG-138
template_version: 3
priority: 1
layer: 3
type: bugfix
status: done
after: [SPEC-006, UX-002]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Traffic Expanded Row Shell Does Not Match UX-002

## Problem

The implemented Traffic expanded row uses generic `.table-row` and
`.detail-panel` styling, but UX-002 defines a dedicated expanded-row shell.
The mismatch makes the request/response detail feel bolted onto the table
instead of part of the selected traffic row.

Observed implementation drift:

- Expanded row uses `.row-expanded` with a 2px left border and generic selected
  background.
- Detail content uses `.detail-panel` with `background: var(--bg-inset)`,
  `border-top`, and uniform `padding: 12px`.
- The metadata row is rendered as a nested `.table-row`, inheriting table-row
  padding, borders, cursor, and hover behavior.

UX-002 reference:

- `UX-002-dashboard-design.pen`, `Phase 0 - Traffic Timeline`
- `row-3-expanded` (`n3DX9`): fill `#58a6ff1a`, left stroke `3px #58a6ff`,
  bottom stroke `1px #58a6ff`, padding `[8,16]`
- `detail-panel` (`4oygT`): fill `#58a6ff1a`, left stroke `3px #58a6ff`,
  padding `[0,16,12,16]`, vertical gap `6`

## Requirements

- [ ] R1: The selected traffic row must use the UX-002 expanded-row shell:
  accent-tinted fill, 3px left accent, and accent bottom stroke.
- [ ] R2: The expanded detail container must visually continue the selected row:
  same accent-tinted fill, same 3px left accent, no generic top border, and
  padding equivalent to `[0,16,12,16]`.
- [ ] R3: Metadata inside the detail panel must not be rendered as a `.table-row`
  and must not inherit table row cursor, hover, column padding, or row borders.
- [ ] R4: The expanded row and detail panel must preserve the existing expand,
  collapse, matched request/response, pending response, and error response
  behavior.
- [ ] R5: The implementation must add focused UI source tests or DOM assertions
  that pin the expanded-row shell classes/structure.

## Acceptance Criteria

- [ ] AC 1: Inspecting an expanded traffic row shows a 3px left accent on both
  the row and detail panel, with no 2px fallback left border.
- [ ] AC 2: The detail panel background is the same accent-tinted selected-row
  surface used by UX-002, not a plain inset panel.
- [ ] AC 3: The metadata bar is a dedicated detail metadata element, not a
  `.table-row`.
- [ ] AC 4: Expanded-row shell tests fail if `.detail-panel` uses generic
  `padding: 12px` or a generic top border for traffic details.
- [ ] AC 5: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`
- Design nodes: `row-3-expanded` (`n3DX9`), `detail-panel` (`4oygT`)
- Current implementation:
  - `internal/web/ui/index.html` - `renderRow`, `renderDetailPanel`
  - `internal/web/ui/ds.css` - `.table-row.row-expanded`, `.detail-panel`
- Existing baseline spec: `SPEC-006`

## Out of Scope

- Changing traffic capture, matching, or API behavior
- Changing table column widths outside the expanded-row shell
- Redesigning the JSON syntax highlighting colors

## Code Pointers

- `internal/web/ui/index.html` - `renderRow(evt, idx)`,
  `renderDetailPanel(entry, matched)`
- `internal/web/ui/ds.css` - row and detail-panel styles near Table and Detail
  Panel sections
- `internal/web/ui_layout_test.go` - source-level UI assertions

## Gap Protocol

- Research-acceptable gaps:
  - Whether to implement dedicated `traffic-detail-*` classes or refactor the
    generic `.detail-panel` class.
  - Exact CSS token names for the UX-002 accent-tinted fill.
- Stop-immediately gaps:
  - Expanded/collapsed behavior regresses.
  - Pending or error detail rows lose their state-specific accent color.
- Max research subagents before stopping: 1
