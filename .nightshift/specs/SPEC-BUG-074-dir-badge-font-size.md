---
id: SPEC-BUG-074
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Dir badge font-size is 11px, design specifies 10px

## Problem

The direction badge text renders at 11px (`--font-size-sm`). The UX-002 design specifies `fontSize: 10` for the dir badge label, which maps to `--font-size-xs` (10px).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Dir badge text node `ABlQv` (r1DirLbl) has `fontSize: 10`.

## Reproduction

1. Open the Timeline tab with traffic data
2. Inspect a direction badge font-size
3. **Actual:** 11px
4. **Expected:** 10px (`--font-size-xs`)

## Root Cause

The `.dir` rule in `internal/web/ui/ds.css` used `font-size: var(--font-size-sm)` (11px) instead of `var(--font-size-xs)` (10px). Fix: replaced `--font-size-sm` with `--font-size-xs` in the `.dir` rule.

## Requirements

- [ ] R1: Dir badge text uses `font-size: var(--font-size-xs)` (10px)

## Acceptance Criteria

- [ ] AC 1: `.dir` badge text renders at 10px
- [ ] AC 2: Badge still fits within the row height without clipping
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `ABlQv` — `fontSize: 10`
- Token mapping: `--font-size-xs: 10px`, `--font-size-sm: 11px`
- Bug location: `internal/web/ui/ds.css` — `.dir` class

## Out of Scope

- Dir badge font-family (SPEC-BUG-073)
- Dir badge icons (SPEC-BUG-072)

## Code Pointers

- `internal/web/ui/ds.css` — `.dir` class (grep for `.dir {`)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
