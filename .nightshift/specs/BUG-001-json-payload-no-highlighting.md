---
id: BUG-001
priority: 1
type: bugfix
status: draft
after: [SPEC-001]
created: 2026-04-04
---

# BUG-001: JSON Payload Has No Syntax Highlighting

## Problem

When expanding a traffic row to see the full JSON payload, it renders as plain monospace text. For large MCP responses (tool results with nested objects, arrays), this is unreadable. JSON syntax highlighting with color-coded keys, strings, numbers, and booleans is essential for a traffic inspector.

## Current Behavior

`prettyJSON()` in `index.html` formats with indentation but renders as plain escaped text inside a `<div class="payload">`.

## Expected Behavior

JSON payloads render with syntax highlighting:
- Keys: accent blue
- Strings: green
- Numbers: orange
- Booleans/null: yellow
- Brackets/braces: muted gray
- Collapsible nested objects (nice-to-have, not required)

## Target Files

- `internal/web/ui/index.html` — add a `highlightJSON()` function, replace `escapeHtml(prettyJSON(...))` calls

## Acceptance Criteria

- [ ] AC-1: JSON payloads in detail view render with color-coded syntax
- [ ] AC-2: Invalid JSON still renders as plain text (no crash)
- [ ] AC-3: No external dependencies — pure JS/CSS in the single HTML file
- [ ] AC-4: Colors match the existing dark theme (use CSS variables)
