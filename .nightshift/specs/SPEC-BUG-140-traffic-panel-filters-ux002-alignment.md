---
id: SPEC-BUG-140
template_version: 3
priority: 3
layer: 3
type: bugfix
status: ready
after: [SPEC-BUG-139]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Traffic Request and Response Panel Filters Do Not Match UX-002

## Problem

The per-panel request/response filters in the Traffic expanded detail panel are
functionally present, but their visual structure does not match UX-002.

Observed implementation drift:

- Each per-panel filter is a rounded `.json-filter.panel-filter` input block.
- The filter strips do not include the search icon visible in the design.
- The filter strips have rounded full borders instead of a full-width strip with
  a bottom divider.
- The placeholder and toggle typography are larger than the design's compact
  request/response filter strip.

UX-002 reference:

- `req-filter` (`mrXZh`) and `res-filter` (`z3cj5`)
- Fill `#161b22`, bottom stroke `1px #21262d`, padding `[4,8]`, gap `6`
- Search icon 11px, muted `#8b949e`
- Placeholder text `Filter request...` / `Filter response...`,
  JetBrains Mono 10px, muted
- Inline compact Text/JQ toggle on the right

## Requirements

- [ ] R1: Request and response filters must render as full-width panel filter
  strips, not standalone rounded input capsules.
- [ ] R2: Each panel filter strip must include an 11px search icon before the
  placeholder/input.
- [ ] R3: Each strip must use the UX-002 fill, bottom divider, padding, gap, and
  compact placeholder typography.
- [ ] R4: Each strip must keep its own independent Text/JQ toggle on the right.
- [ ] R5: Keyboard input and mode switching must remain independent per panel.

## Acceptance Criteria

- [ ] AC 1: Request panel filter starts with a search icon followed by
  `Filter request...` input text.
- [ ] AC 2: Response panel filter starts with a search icon followed by
  `Filter response...` input text.
- [ ] AC 3: The per-panel filters are full-width strips with bottom-only
  divider styling, not rounded bordered boxes.
- [ ] AC 4: Toggling Text/JQ in the request panel does not change the response
  panel mode, and vice versa.
- [ ] AC 5: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`
- Design nodes: `req-filter` (`mrXZh`), `res-filter` (`z3cj5`),
  `Toggle/TextJQ` (`ZpCI9`)
- Current implementation:
  - `internal/web/ui/index.html` - `renderDetailPanel`
  - `internal/web/ui/ds.css` - `.json-filter.panel-filter`,
    `.mode-toggle-sm`
- Related done spec: `SPEC-BUG-008`

## Out of Scope

- Changing shared/global filter behavior.
- Changing jq expression syntax or JSON filtering semantics.
- Changing Tool Browser response filter styling.

## Code Pointers

- `internal/web/ui/index.html` - request/response panel filter markup in
  `renderDetailPanel`
- `internal/web/ui/index.html` - `wireFilterInputs`
- `internal/web/ui/ds.css` - JSON Controls section
- `internal/web/ui_layout_test.go` - source-level assertions

## Gap Protocol

- Research-acceptable gaps:
  - Whether to use one reusable CSS class for both filters or request/response
    modifier classes.
- Stop-immediately gaps:
  - Per-panel Text/JQ filtering becomes shared or non-functional.
  - The panel filters lose focusability or keyboard input.
- Max research subagents before stopping: 1
