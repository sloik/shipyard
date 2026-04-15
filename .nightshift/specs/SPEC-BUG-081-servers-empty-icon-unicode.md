---
id: SPEC-BUG-081
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

# Servers empty state uses Unicode 🖥️, design specifies Lucide server 40px

## Problem

The Servers tab empty state shows a Unicode emoji `&#128421;` (🖥️) inside a `<div class="empty-icon">`. The UX-002 design specifies a Lucide `server` icon at 40×40px with `stroke: var(--text-muted)`.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Empty state node `xCgHC` — icon uses `iconFontFamily: "lucide"`, `iconFontName: "server"`, size 40×40.

## Reproduction

1. Open Shipyard Servers tab with no servers connected
2. Look at the empty state icon
3. **Actual:** Unicode 🖥️ emoji rendered via CSS font-size 32px, opacity 0.5
4. **Expected:** Lucide `server` SVG, 40×40px, stroke color `var(--text-muted)`

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Replace Unicode `&#128421;` with Lucide `server` SVG in Servers empty state
- [ ] R2: Icon size is 40×40px
- [ ] R3: Icon stroke color is `var(--text-muted)`

## Acceptance Criteria

- [ ] AC 1: Servers empty state shows Lucide `server` SVG (not Unicode emoji)
- [ ] AC 2: Icon is 40×40px
- [ ] AC 3: Icon uses `stroke: var(--text-muted)`
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `xCgHC` — `iconFontFamily: "lucide"`, `iconFontName: "server"`, 40×40
- Live: `<div class="empty-icon">&#128421;</div>` with `font-size: 32px; opacity: 0.5`
- Bug location: `internal/web/ui/index.html` — line ~554

## Out of Scope

- Empty state text content or font styles
- Server card layout when servers are present

## Code Pointers

- `internal/web/ui/index.html` — Servers empty state (line ~554, grep for `128421`)
- `internal/web/ui/ds.css` — `.empty-state .empty-icon` (line ~1387)

## Gap Protocol

- Research-acceptable gaps: Lucide SVG path data for server icon
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
