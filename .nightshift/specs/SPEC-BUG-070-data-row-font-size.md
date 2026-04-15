---
id: SPEC-BUG-070
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Data row cells font-size is 13px (md) instead of 12px (base)

## Problem

The `.table-row > *` CSS rule sets `font-size: var(--font-size-md)` (13px). The UX-002 design specifies `fontSize: 12` for data row text nodes (time, server, method, status, latency), which maps to `--font-size-base` (12px).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Data row node (`sxbeT`), text nodes: `RfT5o` (time, fontSize 12), `LB898` (server, fontSize 12), `rmr5f` (method, fontSize 12), latency text `k1nqN` (fontSize 11). All use 12px base size, not 13px.

## Reproduction

1. Open the Timeline tab with traffic data
2. Inspect any data row cell text
3. **Actual:** font-size is 13px (`--font-size-md`)
4. **Expected:** font-size should be 12px (`--font-size-base`)

## Root Cause

`.table-row > *` in `ds.css` was set to `font-size: var(--font-size-md)` (13px) instead of `var(--font-size-base)` (12px). This was a one-character token mismatch — `md` vs `base` — causing all data row cells to render 1px larger than the UX-002 design spec.

## Requirements

- [x] R1: `.table-row > *` uses `font-size: var(--font-size-base)` (12px)

## Acceptance Criteria

- [x] AC 1: `.table-row > *` in `ds.css` specifies `font-size: var(--font-size-base)`
- [x] AC 2: All data row cells in Timeline and History render at 12px base font-size
- [x] AC 3: Specialized cells (pills, badges) that override font-size are not affected
- [x] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, row text nodes all use `fontSize: 12`
- Token mapping: `--font-size-md: 13px`, `--font-size-base: 12px`
- Bug location: `internal/web/ui/ds.css`, `.table-row > *` rule (line ~1024)

## Out of Scope

- Method column font-family (already monospace, correct)
- Latency pill font-size (controlled by `.pill` class)
- Dir badge font-size (SPEC-BUG-074)

## Code Pointers

- `internal/web/ui/ds.css` — `.table-row > *` (line ~1024–1027)

## Gap Protocol

- Research-acceptable gaps: verify pills and badges aren't affected by the base font-size change
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
