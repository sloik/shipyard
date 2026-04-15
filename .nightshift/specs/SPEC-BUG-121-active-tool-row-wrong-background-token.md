---
id: SPEC-BUG-121
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: []
violates: [SPEC-028]
prior_attempts: []
created: 2026-04-15
---

# Active/Selected Tool Row Uses $accent-subtle Background Instead of $row-selected

## Problem

The active/selected tool row in the sidebar uses `var(--accent-subtle)` (#388bfd26 = rgba(56, 139, 253, 0.15)) as background color. SPEC-028 R18/AC 21 specify `$row-selected` (#58a6ff1a = rgba(88, 166, 255, 0.1)) — a different color and opacity.

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)
**Violated criteria:** AC 21 — enabled + selected tool row should have `fill: $row-selected`; R18 — active/selected row `fill: $row-selected`

## Reproduction

1. Open Tools tab → click any tool in the sidebar
2. Inspect the selected row background-color
3. **Actual:** rgba(56, 139, 253, 0.15) = `var(--accent-subtle)` = #388bfd26
4. **Expected:** rgba(88, 166, 255, 0.1) = `var(--row-selected)` = #58a6ff1a

## Root Cause

The `.tool-item.is-active` rule in `internal/web/ui/ds.css` used `var(--accent-subtle)` (#388bfd26) instead of the design-token `var(--row-selected)` (#58a6ff1a) specified by SPEC-028 R18/AC 21. A single wrong token was set when the rule was originally authored.

## Requirements

- [x] R1: Active/selected tool row uses `background: var(--row-selected)` instead of `var(--accent-subtle)`

## Acceptance Criteria

- [x] AC 1: Selected tool row background is `var(--row-selected)` (#58a6ff1a)
- [x] AC 2: AC 21 from SPEC-028 passes
- [x] AC 3: No regressions — hover state still uses `var(--row-hover)`

## Context

- Violated spec: SPEC-028 (Tool & Server Enable/Disable Toggles)
- Design token values: `--accent-subtle: #388bfd26`, `--row-selected: #58a6ff1a` — different RGB base and alpha
- The `.tool-item.is-active` CSS rule uses `background: var(--accent-subtle)` (ds.css line ~1854)

## Out of Scope

- Hover state background (currently var(--row-hover), appears correct)
- Dark/light theme variations

## Code Pointers

- Bug area: `internal/web/ui/ds.css` (line ~1854) — `.tool-item.is-active { background: var(--accent-subtle); }` should be `var(--row-selected)`
- Violated spec: `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
