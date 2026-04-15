---
id: SPEC-BUG-079
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

# Timeline empty state uses Unicode 📥, design specifies Lucide inbox 48px

## Problem

The Timeline tab empty state shows a Unicode emoji `&#128229;` (📥) inside a `<div class="empty-icon">`. The UX-002 design specifies a Lucide `inbox` icon at 48×48px with `stroke: var(--text-muted)`.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Empty state node `13hME` — icon uses `iconFontFamily: "lucide"`, `iconFontName: "inbox"`, size 48×48.

## Reproduction

1. Open Shipyard with no traffic data (or clear filters to show empty state on Timeline)
2. Look at the empty state icon
3. **Actual:** Unicode 📥 emoji rendered via CSS font-size 32px, opacity 0.5
4. **Expected:** Lucide `inbox` SVG, 48×48px, stroke color `var(--text-muted)`

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Replace Unicode `&#128229;` with Lucide `inbox` SVG in Timeline empty state
- [ ] R2: Icon size is 48×48px
- [ ] R3: Icon stroke color is `var(--text-muted)`

## Acceptance Criteria

- [ ] AC 1: Timeline empty state shows Lucide `inbox` SVG (not Unicode emoji)
- [ ] AC 2: Icon is 48×48px
- [ ] AC 3: Icon uses `stroke: var(--text-muted)` (currentColor inheriting from parent)
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `13hME` — `iconFontFamily: "lucide"`, `iconFontName: "inbox"`, 48×48
- Live: `<div class="empty-icon">&#128229;</div>` with `font-size: 32px; opacity: 0.5`
- Bug location: `internal/web/ui/index.html` — line ~71

## Out of Scope

- Empty state text content or font styles
- Empty state card container (covered by tool empty state pattern)

## Code Pointers

- `internal/web/ui/index.html` — Timeline empty state (line ~71, grep for `128229`)
- `internal/web/ui/ds.css` — `.empty-state .empty-icon` (line ~1387)

## Gap Protocol

- Research-acceptable gaps: Lucide SVG path data for inbox icon
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
