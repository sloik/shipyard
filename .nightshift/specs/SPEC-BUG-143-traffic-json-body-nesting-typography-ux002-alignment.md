---
id: SPEC-BUG-143
template_version: 3
priority: 6
layer: 3
type: bugfix
status: in_progress
after: [SPEC-BUG-141]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Traffic JSON Bodies Use Generic Code-Block Nesting Instead of UX-002 Split-View Body

## Problem

The request/response JSON bodies inside expanded Traffic details are nested
inside generic `.code-block` and `.json-viewer code-body` structures. UX-002's
split-view body is a direct panel body under the colored header, with its own
dark fill, compact padding, line spacing, and line-number metrics.

Observed implementation drift:

- Each panel wraps the header/body in `.code-block`, creating an extra border
  and radius inside the already-bordered split view.
- `.json-viewer` applies generic border, radius, 12px font, 1.6 line height,
  and larger padding.
- UX-002 body rows use JetBrains Mono 11px, line-number width 20, row gap 2,
  and compact body padding.
- The nested code-block makes the panel look like two code cards inside a
  split-view instead of a single integrated split-view component.

UX-002 reference:

- `srBody` (`rJHR1`) and `resBody` (`kyYV1`)
- Fill `#010409`, clip true, vertical gap `2`, height `160`, padding
  `[4,10,4,6]`
- JSON line numbers: width `20`, right-aligned, color `#8b949e`,
  JetBrains Mono 11px
- JSON line content: JetBrains Mono 11px, color by value class

## Requirements

- [ ] R1: Traffic split-view request/response panel bodies must not be nested
  in generic `.code-block` cards.
- [ ] R2: Panel bodies must use the UX-002 dark inset body fill, compact
  padding, row gap, and scroll behavior.
- [ ] R3: Traffic panel JSON line numbers must use the UX-002 width and compact
  typography within split-view bodies.
- [ ] R4: Traffic panel JSON content must keep existing syntax highlighting,
  recursive string expansion, key sorting, text filter, and jq filter behavior.
- [ ] R5: Tests must assert that Traffic split-view bodies use dedicated panel
  body classes and do not emit nested `.code-block` wrappers.

## Acceptance Criteria

- [ ] AC 1: Request and response JSON bodies are direct descendants of their
  panel structure after the panel header, without an intermediate `.code-block`.
- [ ] AC 2: Split-view body styling uses compact 11px monospace JSON rows and
  20px line-number columns for Traffic detail panels.
- [ ] AC 3: The split-view itself remains the only outer bordered/radius
  container around request and response bodies.
- [ ] AC 4: Text filtering and jq filtering continue to update the same JSON
  body content.
- [ ] AC 5: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`
- Design nodes: `srBody` (`rJHR1`), `resBody` (`kyYV1`), `split-view`
  (`lCLtt`)
- Current implementation:
  - `internal/web/ui/index.html` - panel body HTML in `renderDetailPanel`
  - `internal/web/ui/ds.css` - `.code-block`, `.json-viewer`,
    `.json-line`, `.json-line .ln`
- Related specs: `SPEC-BUG-004`, `SPEC-036`, `SPEC-040`, `SPEC-042`,
  `SPEC-044`

## Out of Scope

- Changing JSON syntax color tokens globally.
- Changing Tool Browser response body metrics.
- Changing diff-view body metrics.

## Code Pointers

- `internal/web/ui/index.html` - `highlightJSON`, `renderDetailPanel`,
  `wireFilterInputs`
- `internal/web/ui/ds.css` - Code, Panels, JSON Viewer, and JSON Controls
  sections
- `internal/web/ui_layout_test.go` - source-level assertions

## Gap Protocol

- Research-acceptable gaps:
  - Whether to add scoped `.traffic-json-viewer` classes or modifier classes
    on `.json-viewer`.
- Stop-immediately gaps:
  - Existing JSON filtering or jq filtering breaks.
  - Large JSON payloads expand the detail panel instead of scrolling.
- Max research subagents before stopping: 1
