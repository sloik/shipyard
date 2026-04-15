---
id: SPEC-BUG-092
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

# Tool browser sidebar items are 13px, design likely specifies 12px

## Problem

Tool browser sidebar `.tool-item` elements render at `font-size: 13px` (`--font-size-md`). The design data row cells use `fontSize: 12` for most content. The sidebar items should use `--font-size-base` (12px) for consistency with the design system.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tool sidebar items should match the design's body text size (12px).

## Reproduction

1. Open Tools tab, inspect a tool name in the sidebar list
2. **Actual:** font-size 13px
3. **Expected:** font-size 12px (`--font-size-base`)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Tool sidebar items use `font-size: var(--font-size-base)` (12px)

## Acceptance Criteria

- [ ] AC 1: `.tool-item` text renders at 12px
- [ ] AC 2: Tool names are still readable and not clipped
- [ ] AC 3: `go build ./...` passes

## Context

- Live: `.tool-item { font-size: 13px }`, color text-secondary, padding 6px 12px 6px 24px
- Design: body text content uses fontSize 12 consistently

## Out of Scope

- Tool sidebar width or padding
- Tool detail panel styling

## Code Pointers

- `internal/web/ui/ds.css` — `.tool-item` rules
- `internal/web/ui/index.html` — tool sidebar structure

## Gap Protocol

- Research-acceptable gaps: exact design node for tool sidebar items
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
