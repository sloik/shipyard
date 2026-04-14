---
id: SPEC-BUG-051
template_version: 2
priority: 2
layer: 2
type: bugfix
status: ready
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-14
---

# Server count pill in header missing Lucide server icon

## Problem

The server count pill in the header right group shows only text (e.g. "1 server"). The UX-002 design shows a Lucide `server` icon (12px, `--text-muted` color) to the left of the count text, inside a pill with `--bg-raised` background and `--border-default` border.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar right group, node `3xCw4` (server-count) contains a Lucide "server" icon_font node (`E0os7`) at 12×12px, fill `#8b949e`.

## Reproduction

1. Open any page in Shipyard UI
2. Look at the server count pill in the header (right side, shows "1 server")
3. **Actual:** Plain text inside a bordered pill, no icon
4. **Expected:** Lucide `server` icon (12px, `--text-muted`) + count text inside the pill

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Server count pill contains a Lucide `server` icon before the text
- [ ] R2: Icon is 12px, colored `var(--text-muted)`

## Acceptance Criteria

- [ ] AC 1: A Lucide `server` icon appears inside the server count pill, before the text
- [ ] AC 2: Icon is 12px in size
- [ ] AC 3: Icon color is `var(--text-muted)`
- [ ] AC 4: Pill styling (background, border, border-radius) remains unchanged
- [ ] AC 5: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `3xCw4` (server-count) — `cornerRadius: 100, fill: #1c2128, gap: 4, padding: [4, 10], stroke: 1px #30363d`; child `E0os7` — Lucide "server" icon 12×12px, fill #8b949e
- Bug location: `internal/web/ui/index.html`, line 26 — `<a href="#servers" id="server-count" class="badge badge-neutral">`

## Out of Scope

- Server count update logic (works correctly)
- Pill positioning or spacing

## Code Pointers

- `internal/web/ui/index.html` — server-count element (line 26)
- `internal/web/ui/ds.css` — `.badge-neutral` rule

## Gap Protocol

- Research-acceptable gaps: Lucide icon loading pattern in the codebase
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
