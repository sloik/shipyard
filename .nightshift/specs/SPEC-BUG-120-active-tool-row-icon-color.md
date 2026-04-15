---
id: SPEC-BUG-120
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

# Active/Selected Sidebar Tool Row Icon Uses $text-muted Instead of $accent-fg

## Problem

When a tool is selected in the sidebar, the wrench icon color remains `var(--text-muted)` (#8b949e, rgb(139, 148, 158)). SPEC-028 R16/AC 21 specify that the active/selected row icon should use `$accent-fg` (#58a6ff, rgb(88, 166, 255)).

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)
**Violated criteria:** AC 21 — enabled + selected tool row should have icon fill `$accent-fg`; R18 — active/selected row icon fill `$accent-fg`

## Reproduction

1. Open Tools tab → click any tool in the sidebar to select it
2. Inspect the icon element (first child span) on the selected row
3. **Actual:** color is rgb(139, 148, 158) = `$text-muted`
4. **Expected:** color is rgb(88, 166, 255) = `$accent-fg`

## Root Cause

The tool row icon span in `index.html` used a hardcoded inline `color:var(--text-muted)` style with no class, so the `.tool-item.is-active` CSS rule had no way to target and override it for the selected state. Fix: added `class="tool-icon"` to the span (removing the inline color), then added `.tool-item .tool-icon { color: var(--text-muted); }` and `.tool-item.is-active .tool-icon { color: var(--accent-fg); }` in `ds.css`.

## Requirements

- [x] R1: Active/selected tool row icon uses `var(--accent-fg)` color

## Acceptance Criteria

- [x] AC 1: Selected tool row icon renders in `$accent-fg` (#58a6ff)
- [x] AC 2: Non-selected tool icons remain `$text-muted`
- [x] AC 3: AC 21 from SPEC-028 passes
- [x] AC 4: No regressions

## Context

- Violated spec: SPEC-028 (Tool & Server Enable/Disable Toggles)
- The icon color is set inline as `color:var(--text-muted)` in the tool row HTML and is not overridden for the active state

## Out of Scope

- Replacing emoji icon with SVG (separate bug BUG-122)
- Detail panel icon color (already correct — uses stroke=var(--accent-fg))

## Code Pointers

- Bug area: `internal/web/ui/index.html` (line ~2154) — icon span has hardcoded `color:var(--text-muted)`
- CSS rule: `internal/web/ui/ds.css` (line ~1853) — `.tool-item.is-active` sets `color: var(--text-primary)` on the row but doesn't target the icon specifically
- Violated spec: `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
