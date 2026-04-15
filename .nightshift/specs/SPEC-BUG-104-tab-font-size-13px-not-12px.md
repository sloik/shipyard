---
id: SPEC-BUG-104
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

# Nav tab labels are 13px, design specifies 12px

## Problem

Navigation tab labels render at `font-size: 13px`. The UX-002 design specifies `fontSize: $font-size-base` (12px) for tab labels (both active and default states).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tab labels use `$font-size-base` (12px) — nodes `qCfG0`, `a3bmc`, `AjtgM`, `jRwzp`, etc.

## Reproduction

1. Open any page, inspect a nav tab label
2. **Actual:** font-size 13px
3. **Expected:** font-size 12px

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Nav tab labels use `font-size: var(--font-size-base)` (12px)

## Acceptance Criteria

- [ ] AC 1: Default tab labels render at 12px
- [ ] AC 2: Active tab label renders at 12px
- [ ] AC 3: Tab labels remain readable
- [ ] AC 4: `go build ./...` passes

## Context

- Design: tab label nodes use `fontSize: "$font-size-base"` which resolves to 12px
- Live: `.tab` class applies font-size 13px (likely `--font-size-md`)
- Both active (fontWeight 600) and default (fontWeight 500) tabs have this issue

## Out of Scope

- Tab icon size
- Tab padding or height (SPEC-BUG-106)

## Code Pointers

- `internal/web/ui/ds.css` — `.tab` rule
- `internal/web/ui/index.html` — nav tab links

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
