---
id: SPEC-BUG-123
template_version: 2
priority: 3
layer: 2
type: bugfix
status: ready
after: []
violates: [SPEC-028]
prior_attempts: []
created: 2026-04-15
---

# Tool Detail Title Row Left Wrapper Gap Is 10px Instead of 8px

## Problem

The left wrapper (icon + tool name + server badge) in the tool detail panel title row has `gap: 10px`. SPEC-028 R29 specifies `gap: 8` for the left wrapper frame in the detail title row.

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)
**Violated criteria:** R29 — detail title row left wrapper has `gap: 8`; AC 18 — tool detail title row layout matches design

## Reproduction

1. Open Tools tab → select any tool → inspect the detail panel title row
2. Inspect the left wrapper div (containing icon, tool name, server badge)
3. **Actual:** gap is 10px
4. **Expected:** gap is 8px

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Detail title row left wrapper uses `gap: 8px`

## Acceptance Criteria

- [ ] AC 1: Left wrapper div in detail title row has gap 8px
- [ ] AC 2: AC 18 from SPEC-028 passes
- [ ] AC 3: No regressions — icon, name, and badge still properly spaced

## Context

- Violated spec: SPEC-028 (Tool & Server Enable/Disable Toggles)
- The gap is set inline in the HTML template

## Out of Scope

- Sidebar tool row gap (already correct at 8px)
- Detail title row justifyContent (already correct: space-between)

## Code Pointers

- Bug area: `internal/web/ui/index.html` (line ~187) — inline style `gap:10px` should be `gap:8px`
- Violated spec: `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
