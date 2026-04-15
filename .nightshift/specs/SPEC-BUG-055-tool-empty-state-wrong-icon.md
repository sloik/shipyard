---
id: SPEC-BUG-055
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: [SPEC-BUG-055-attempt-1]
created: 2026-04-14
---

# Tool browser empty state uses Unicode wrench emoji instead of Lucide mouse-pointer-click icon

## Problem

The "No tool selected" empty state in the Tool Browser shows a Unicode wrench character (`&#128295;` / 🔧). The UX-002 design specifies a Lucide `mouse-pointer-click` icon at 40×40px in `--text-muted` color. The empty state also lacks the bordered card container shown in the design.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Phase 1 No Tool Selected frame (`KV32h`), empty state node (`b6Dqw`) contains a Lucide `mouse-pointer-click` icon_font node (`M8Zh3`) at 40×40px, fill `#8b949e`. The container has `cornerRadius: 8, padding: 32, stroke: 1px #21262d`.

## Reproduction

1. Open the Tools tab in Shipyard UI without selecting any tool
2. Look at the empty state in the main content area
3. **Actual:** Unicode wrench emoji (🔧) at 32px with 0.5 opacity, no border card
4. **Expected:** Lucide `mouse-pointer-click` icon at 40px in `--text-muted` color, inside a card with 8px radius and `--border-muted` border, 32px padding

## Root Cause

The empty state `<div id="tools-empty">` contained a Unicode wrench character instead of a Lucide SVG icon, and lacked a card container with border styling. Attempt 1 correctly replaced the icon with Lucide `mouse-pointer-click` SVG at 40px / `var(--text-muted)`, but did NOT add the bordered card wrapper (AC 4).

## Prior Attempt Notes

**SPEC-BUG-055-attempt-1:** R1 and R2 done (icon replaced with Lucide SVG). R3 NOT done — the empty state content still sits directly inside `#tools-empty` with no card container. AC 1–3 pass, AC 4 fails. The fix must wrap the icon + title + description in a `<div>` with `border: 1px solid var(--border-muted); border-radius: 8px; padding: 32px`.

## Requirements

- [x] R1: Empty state icon is a Lucide `mouse-pointer-click` icon, not a Unicode wrench
- [x] R2: Icon is 40px, colored `var(--text-muted)`
- [x] R3: Empty state content is wrapped in a bordered card (border-radius 8px, 1px solid `--border-muted`, padding 32px)

## Acceptance Criteria

- [x] AC 1: Empty state displays Lucide `mouse-pointer-click` icon
- [x] AC 2: Icon is 40px in size
- [x] AC 3: Icon color is `var(--text-muted)` (no opacity override)
- [x] AC 4: Empty state content is inside a container with `border: 1px solid var(--border-muted); border-radius: 8px; padding: 32px`
- [x] AC 5: Title and description text remain unchanged
- [x] AC 6: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `b6Dqw` (empty state card in No Tool Selected frame `KV32h`) — `cornerRadius: 8, gap: 12, padding: 32, stroke: 1px #21262d`; child `M8Zh3` — Lucide "mouse-pointer-click", 40×40, fill #8b949e
- Bug location: `internal/web/ui/index.html`, `<div id="tools-empty">` (line ~156)

## Out of Scope

- Tool browser sidebar styling
- Empty state for other views (Timeline, etc.)

## Code Pointers

- `internal/web/ui/index.html` — `<div id="tools-empty">` (lines 156–160)
- `internal/web/ui/ds.css` — `.empty-state` rules

## Gap Protocol

- Research-acceptable gaps: Lucide icon class pattern for static HTML elements
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
