---
id: SPEC-BUG-091
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: [SPEC-BUG-087]
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Latency column cell is not right-aligned (justifyContent: end)

## Problem

The latency column cell content is left-aligned. The UX-002 design specifies `justifyContent: end` for the `cell-latency` frame, meaning the latency pill should be right-aligned within the cell.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** `cell-latency` (1I5OC) has `justifyContent: end`.

## Reproduction

1. Open Timeline tab, inspect a latency cell alignment
2. **Actual:** Latency text/pill is left-aligned within the cell
3. **Expected:** Latency pill is right-aligned

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Latency column cells use `justify-content: flex-end` or `text-align: right`

## Acceptance Criteria

- [ ] AC 1: Latency values are right-aligned within their column cell
- [ ] AC 2: Latency header label is also right-aligned (matching `thLatency justifyContent: end`)
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: `cell-latency` (1I5OC) — `justifyContent: end`, width 80
- Design reference: `thLatency` (m06CC) — `justifyContent: end`, width 70
- Live: text-align appears to be right already (textAlign: "right" found in sweep), verify after pill fix

## Out of Scope

- Latency pill styling (SPEC-BUG-087)
- Latency font or color

## Code Pointers

- `internal/web/ui/ds.css` — `[data-col="latency"]` or latency cell rules

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
