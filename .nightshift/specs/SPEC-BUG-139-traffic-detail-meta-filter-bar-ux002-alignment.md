---
id: SPEC-BUG-139
template_version: 3
priority: 2
layer: 3
type: bugfix
status: ready
after: [SPEC-BUG-138]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Traffic Detail Metadata and Shared Filter Bar Drift from UX-002

## Problem

The Traffic expanded detail panel has a shared metadata row and a shared JSON
filter row above the request/response split view. Those elements exist in
UX-002, but the implementation uses generic components that do not match the
design.

Observed implementation drift:

- Metadata is rendered as `<div class="table-row">`, so it inherits table-row
  borders, cursor, hover affordance, and cell padding.
- Shared JSON filter is rendered as a full-width `.json-filter` with no search
  icon, no 280px input capsule, no separate Text/JQ toggle, and no spacer/match
  count slot.
- The shared filter visually competes with the per-panel filters rather than
  matching the compact UX-002 `json-filter-bar`.

UX-002 reference:

- `meta-bar` (`8yx6z`): horizontal row, gap `16`, padding `[8,0]`
- `json-filter-bar` (`qiHrm`): horizontal row, gap `8`
- `jfInput` (`kkMtq`): width `280`, fill `#0d1117`, stroke `#30363d`,
  corner radius `6`, padding `[5,10]`, search icon, JetBrains Mono placeholder
- `jfMode` (`EY7mp`): separate Text/JQ segmented toggle after the input
- `jfSpacer` and optional hidden `jfMatchCount`

## Requirements

- [ ] R1: Replace the metadata `.table-row` with a dedicated metadata bar that
  follows UX-002 spacing and does not behave like a clickable data row.
- [ ] R2: The shared JSON filter row must be composed as input capsule, Text/JQ
  toggle, spacer, and optional match count slot, matching UX-002 order.
- [ ] R3: The shared input must include a search icon and placeholder styling
  consistent with `jfInput`.
- [ ] R4: The shared Text/JQ toggle must remain functionally connected to the
  existing text and jq filtering logic.
- [ ] R5: Tests must assert the shared filter bar is structurally separate from
  per-panel filters and from data table rows.

## Acceptance Criteria

- [ ] AC 1: Expanded traffic details contain a metadata bar element with no
  `.table-row` class.
- [ ] AC 2: The shared filter bar contains a search icon, a 280px filter input,
  a separate Text/JQ toggle, a flex spacer, and a hidden or future-ready match
  count slot.
- [ ] AC 3: Shared Text/JQ filtering still applies to both request and response
  viewers.
- [ ] AC 4: Per-panel filters still apply independently after using the shared
  filter.
- [ ] AC 5: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`
- Design nodes: `meta-bar` (`8yx6z`), `json-filter-bar` (`qiHrm`),
  `jfInput` (`kkMtq`), `jfMode` (`EY7mp`)
- Current implementation:
  - `internal/web/ui/index.html` - `renderDetailPanel`, `wireFilterInputs`
  - `internal/web/ui/ds.css` - `.json-filter`, `.mode-toggle`, `.table-row`
- Related specs: `SPEC-BUG-005`, `SPEC-BUG-008`, `SPEC-041`

## Out of Scope

- Adding a real match-count feature if none exists yet; the slot may remain
  hidden as in the design.
- Changing jq evaluator semantics.
- Changing per-panel request/response filters beyond preserving compatibility.

## Code Pointers

- `internal/web/ui/index.html` - shared filter HTML in `renderDetailPanel`
- `internal/web/ui/index.html` - `wireFilterInputs`, mode-toggle click handler
- `internal/web/ui/ds.css` - JSON Controls section
- `internal/web/ui_layout_test.go` - source-level tests for expected structure

## Gap Protocol

- Research-acceptable gaps:
  - Exact class names for the new metadata and shared filter row.
  - Whether match-count is hidden with `display:none` or omitted until needed.
- Stop-immediately gaps:
  - Existing text/JQ filters stop working.
  - The shared filter becomes visually indistinguishable from per-panel filters.
- Max research subagents before stopping: 1
