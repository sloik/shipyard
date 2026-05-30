---
id: FART-SCR-001
template_version: 4
priority: 4
layer: 3
type: feature
status: in_progress
after: [SPEC-BUG-139]
nfrs: [SPEC-NFR-001]
devkb_required: [frontend.md, testing.md, go.md]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Live Shared JSON Filter Match Counts

## Problem

SPEC-BUG-139 added the UX-002 shared JSON filter match-count slot for the
Traffic detail request/response viewers, but the slot remains hidden and does
not display live feedback. Users can filter both JSON panes from the shared
control, but they cannot tell how many request/response matches remain without
visually scanning the panes.

## Requirements

- [ ] R1: Populate the existing shared `json-filter-match-count` slot with live
  match feedback when the shared filter is active.
- [ ] R2: The match count must reflect both request and response viewers after
  shared Text/JQ filtering runs.
- [ ] R3: The match-count slot must remain hidden or empty when no shared filter
  is active.
- [ ] R4: Invalid JQ expressions must keep the existing error behavior and must
  not display stale match counts.
- [ ] R5: Tests must cover active, empty, and invalid-filter count states.

## Acceptance Criteria

- [ ] AC 1: Typing a shared text filter updates the shared match-count slot with
  a non-empty count derived from the request and response panes.
- [ ] AC 2: Switching the shared filter between Text and JQ mode recomputes the
  count without changing per-panel filter state.
- [ ] AC 3: Clearing the shared filter hides or empties the match-count slot.
- [ ] AC 4: Entering an invalid JQ expression hides or clears the count and
  preserves the current validation/error behavior.
- [ ] AC 5: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Origin: Suggested follow-up from the SPEC-BUG-139 Nightshift report.
- Existing slot:
  - `internal/web/ui/index.html` - `json-filter-match-count`
  - `internal/web/ui/ds.css` - `.json-filter-match-count`
- Filtering logic:
  - `internal/web/ui/index.html` - `wireFilterInputs`
  - `internal/web/ui/index.html` - shared filter mode-toggle handler
- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`

## Live Execution Checklist

- [ ] Start the dashboard and open a Traffic detail row with request and
  response JSON bodies.
- [ ] Type a shared text filter that matches one or both panes and confirm the
  count updates.
- [ ] Switch the shared control to JQ mode and confirm the count recomputes for
  valid expressions.
- [ ] Clear the shared filter and confirm the slot no longer displays a count.
- [ ] Enter an invalid JQ expression and confirm existing error feedback remains
  visible while no stale count is shown.

## Out of Scope

- Adding match counts to per-panel request/response filters.
- Changing jq expression semantics.
- Changing Traffic row capture or replay behavior.

## Gap Protocol

- Research-acceptable gaps:
  - Exact count wording, such as `3 matches` versus `3 shown`.
  - Whether the count should aggregate both panes or show request/response
    subtotals, as long as the implementation is tested and understandable.
- Stop-immediately gaps:
  - The shared filter stops applying to both viewers.
  - Invalid JQ expressions leave stale match counts visible.
- Max research subagents before stopping: 1
