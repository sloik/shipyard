---
id: SPEC-BUG-098
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

# Method column renders as code block, design specifies plain text

## Problem

The method column in timeline rows renders each value as a styled code block: dark background (`#010409`), border (`1px solid #21262d`), padding (`8px 16px`), and `border-radius: 4px`. The UX-002 design shows method values as **plain text** — just `JetBrains Mono 12px normal` in `$text-primary` (#e6edf3) with no background, no border, and no extra padding.

This creates a visually heavy, cluttered row that doesn't match the clean table design.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** `cell-method` frames (e.g. `C0Ux7`, `62NDq`, `0dMJE`) contain only a plain text node — no fill, no stroke, no cornerRadius, no padding on the cell frame.

## Reproduction

1. Open Timeline tab, look at the Method column in any data row
2. **Actual:** Each method value ("tools/list", "tools/call", etc.) is wrapped in a dark code-block box with background, border, padding, border-radius
3. **Expected:** Plain text, no surrounding box — just the method name in JetBrains Mono

## Root Cause

Both timeline row templates (main timeline and history tab) wrapped the method span in `class="code-inline"`, which adds dark background, border, border-radius, and padding. The fix replaces `code-inline` with a new `method-cell` class in both JS row templates, and adds a `.method-cell` rule to `ds.css` with only the required styling: `font-family: var(--font-mono); font-size: 12px; color: var(--text-primary);` — no background, border, or padding. The `.code-inline` class remains unchanged for detail panel and modal usage.

## Requirements

- [x] R1: Method column cells display as plain text, no background
- [x] R2: No border or border-radius on method cell content
- [x] R3: No extra padding around method text beyond normal cell padding
- [x] R4: Font remains JetBrains Mono 12px, color text-primary

## Acceptance Criteria

- [x] AC 1: Method cell has no background color (transparent)
- [x] AC 2: Method cell has no border
- [x] AC 3: Method cell has no border-radius
- [x] AC 4: Method text is JetBrains Mono 12px normal, color #e6edf3
- [x] AC 5: Row height doesn't change significantly (removing padding may reduce it)
- [x] AC 6: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — `cell-method` (mhUwb, 9smwl) and row instances (`r1Method` C0Ux7, `r2Method` 62NDq, `r3Method` 0dMJE, etc.)
- Design: frame with `width: fill_container`, no fill/stroke/padding/cornerRadius. Child text node: `fontFamily: "JetBrains Mono"`, `fontSize: 12`, `fontWeight: normal`, `fill: $text-primary`
- Live: `.code-inline` class applied to method span, which adds `background: #010409`, `border: 1px solid #21262d`, `padding: 8px 16px`, `border-radius: 4px`
- The `.code-inline` class is meant for code display in the detail panel, not for table cell content

## Out of Scope

- Method column width
- Response rows showing "—" (dash) — same fix applies
- `.code-inline` usage in the detail panel (should remain styled there)

## Code Pointers

- `internal/web/ui/ds.css` — `.code-inline` rule, `.table-row` cell styling
- `internal/web/ui/index.html` — timeline row template / JS rendering
- May need a different class or override for `.table-row .code-inline`

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
