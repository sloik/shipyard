---
id: SPEC-BUG-116
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

# Filter bar labels use font-size 11px, design specifies 12px

## Problem

The filter bar labels ("Server", "Method", "Direction") in the Traffic Timeline view use `font-size: var(--font-size-sm)` which resolves to 11px. The UX-002 design InputGroup/Labeled component (`7v5hP`) specifies `fontSize: 12` for labels.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Filter bar labels should use `--font-size-base` (12px), not `--font-size-sm` (11px).

## Reproduction

1. Open the Traffic tab, inspect any filter label (Server, Method, Direction)
2. **Actual:** font-size: 11px
3. **Expected:** font-size: 12px

## Root Cause

The `.input-label` class in `internal/web/ui/ds.css` had `font-size: var(--font-size-sm)` (11px) instead of `font-size: var(--font-size-base)` (12px). Filter bar labels ("Server", "Method", "Direction") use the `.input-label` class, so they inherited the wrong size.

## Requirements

- [x] R1: Filter bar labels use `font-size: var(--font-size-base)` (12px)

## Acceptance Criteria

- [x] AC 1: "Server" label renders at 12px
- [x] AC 2: "Method" label renders at 12px
- [x] AC 3: "Direction" label renders at 12px
- [x] AC 4: `go build ./...` passes

## Context

- Design: InputGroup/Labeled (`7v5hP`) label: fontSize 12, fontWeight 500, textColor #b1bac4
- Live: filter labels at 11px (--font-size-sm)
- Fix: change the label font-size rule from `--font-size-sm` to `--font-size-base`

## Out of Scope

- Label color (already covered by BUG-095)
- Input/select font-size (BUG-117)

## Code Pointers

- `internal/web/ui/ds.css` — label rule inside `.input-group` or filter bar

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
