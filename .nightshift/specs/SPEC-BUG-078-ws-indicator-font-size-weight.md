---
id: SPEC-BUG-078
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

# WS indicator font-size is 11px and font-weight 400, design specifies 12px/500

## Problem

The `.ws-indicator` text renders at `font-size: var(--font-size-sm)` (11px) with default `font-weight: 400`. The UX-002 design specifies `fontSize: 12` (`--font-size-base`) and `fontWeight: 500` for the indicator text.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Indicator text node `syr1q` (label "Live") has `fontSize: 12, fontWeight: 500`.

## Reproduction

1. Open Shipyard with an active connection (Live state)
2. Inspect the ws-indicator font-size and font-weight
3. **Actual:** font-size 11px, font-weight 400
4. **Expected:** font-size 12px (`--font-size-base`), font-weight 500

## Root Cause

`.ws-indicator` used `font-size: var(--font-size-sm)` (11px) and had no `font-weight` declaration (defaulting to 400). The UX-002 design specifies the indicator text at `fontSize: 12` (mapped to `--font-size-base`) and `fontWeight: 500`.

## Requirements

- [ ] R1: `.ws-indicator` uses `font-size: var(--font-size-base)` (12px)
- [ ] R2: `.ws-indicator` uses `font-weight: 500`

## Acceptance Criteria

- [ ] AC 1: WS indicator text renders at 12px
- [ ] AC 2: WS indicator text renders at font-weight 500
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `syr1q` — `fontSize: 12, fontWeight: 500`
- Live computed: `fontSize: 11px, fontWeight: 400`
- Bug location: `internal/web/ui/ds.css` — `.ws-indicator` (line ~713)

## Out of Scope

- WS indicator live text color (SPEC-BUG-077)
- WS indicator dot size (already correct at 8px)

## Code Pointers

- `internal/web/ui/ds.css` — `.ws-indicator` (grep for `.ws-indicator {`)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
