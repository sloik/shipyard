---
id: SPEC-BUG-122
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

# Sidebar Tool Rows Use Unicode Wrench Emoji Instead of SVG Icon

## Problem

Tool rows in the sidebar use the Unicode wrench emoji (&#128295; / 🔧) rendered in a 14×14 span. The design (UX-002) and SPEC-028 R15 specify a Lucide `wrench` SVG icon at 14×14. The detail panel title row already uses the correct SVG wrench icon — only the sidebar rows are inconsistent.

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)
**Violated criteria:** R15 — wrench icon 14×14 in sidebar tool row; design shows Lucide SVG wrench across all screens

## Reproduction

1. Open Tools tab → inspect the icon on any sidebar tool row
2. **Actual:** Unicode emoji character &#128295; (🔧) in a span
3. **Expected:** Lucide wrench SVG icon at 14×14, same style as the detail panel icon but smaller

## Root Cause

SPEC-BUG-060 fixed the detail panel wrench icon (line ~188) from Unicode emoji to Lucide SVG but did not update the sidebar tool row template (line ~2154), which still used `&#128295;` in a styled `<span>`. The fix replaces the `<span>` with an inline Lucide `wrench` SVG at 14×14 using `stroke="currentColor"` and `class="tool-icon"` to inherit color from CSS.

## Requirements

- [x] R1: Sidebar tool rows use a Lucide `wrench` SVG icon at 14×14 instead of Unicode emoji
- [x] R2: Icon color matches design token: `$text-muted` for default rows, `$accent-fg` for active rows

## Acceptance Criteria

- [x] AC 1: Sidebar tool icon is an SVG (not emoji), 14px × 14px
- [x] AC 2: Icon renders consistently across browsers (SVG vs emoji rendering varies)
- [x] AC 3: Icon uses `stroke="currentColor"` or similar to inherit color from parent/CSS
- [x] AC 4: No regressions — conflict rows still show warning icon &#9888;

## Context

- Violated spec: SPEC-028 (Tool & Server Enable/Disable Toggles)
- Related done bug: SPEC-BUG-060 fixed the detail panel wrench from Unicode to SVG, but the sidebar was not included in that fix
- The detail panel already has the correct SVG at 18×18 (index.html line ~188) — the sidebar should use the same SVG at 14×14

## Out of Scope

- Detail panel icon (already SVG — correct)
- Icon color for active rows (covered by SPEC-BUG-120)

## Code Pointers

- Bug area: `internal/web/ui/index.html` (line ~2154) — `&#128295;` emoji in sidebar tool row
- Reference: `internal/web/ui/index.html` (line ~188) — correct SVG usage in detail panel
- Violated spec: `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
