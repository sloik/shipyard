---
id: SPEC-BUG-118
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

# Sidebar Tool Name Inline Style Uses font-size-sm (11px) Instead of font-size-base (12px)

## Problem

The tool name `<span>` in each sidebar tool row has an inline `font-size:var(--font-size-sm)` which renders at 11px. SPEC-028 R15 specifies the tool name should use `$font-size-base` (12px). The `.tool-item` CSS class correctly sets `font-size: var(--font-size-base)` (fixed by BUG-092), but the inline style on the name span overrides it.

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)
**Violated criteria:** AC 16 — tool list sidebar row layout should match design; R15 — tool name text uses `$font-size-base`

## Reproduction

1. Open Tools tab → inspect any tool name text in the sidebar
2. **Actual:** font-size is 11px (var(--font-size-sm) from inline style)
3. **Expected:** font-size is 12px (var(--font-size-base) per design)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Sidebar tool name span uses `font-size: var(--font-size-base)` (12px)

## Acceptance Criteria

- [ ] AC 1: Tool name text in sidebar renders at 12px
- [ ] AC 2: AC 16 from SPEC-028 passes (tool row layout matches design)
- [ ] AC 3: No regressions — tool names still readable, not clipped

## Context

- Violated spec: SPEC-028 (Tool & Server Enable/Disable Toggles)
- Prior fix: SPEC-BUG-092 fixed the `.tool-item` CSS class from 13px to 12px, but the inline style on the name span was not updated

## Out of Scope

- Tool name font-family changes (already correct: var(--font-mono))
- Tool detail panel font sizes (separate element)

## Code Pointers

- Bug area: `internal/web/ui/index.html` (line ~2156) — inline style `font-size:var(--font-size-sm)`
- CSS class: `internal/web/ui/ds.css` (line ~1838) — `.tool-item` already has correct `font-size: var(--font-size-base)`
- Violated spec: `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
