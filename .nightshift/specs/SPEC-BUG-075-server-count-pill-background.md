---
id: SPEC-BUG-075
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

# Server count pill has transparent background, design specifies bg-raised

## Problem

The `#server-count` badge has a transparent background. The UX-002 design specifies `fill: #1c2128` (--bg-raised) for the server-count pill.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Server-count node in Header/AppBar right group — `fill: "#1c2128"` (bg-raised), `padding: [4, 10]`, `cornerRadius: 100`, `stroke: 1px #30363d`.

## Reproduction

1. Open any page in Shipyard UI
2. Inspect the server count pill in the header (e.g., "1 server")
3. **Actual:** Background is transparent
4. **Expected:** Background should be `var(--bg-raised)` (#1c2128)

## Root Cause

`.badge-neutral` in `ds.css` had `background: transparent` hardcoded. Changed to `background: var(--bg-raised)` per UX-002 spec.

## Requirements

- [ ] R1: Server count pill has `background: var(--bg-raised)`

## Acceptance Criteria

- [ ] AC 1: `#server-count` (or `.badge-neutral` when used for server count) has `background: var(--bg-raised)`
- [ ] AC 2: Pill renders with visible dark background against the header
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, server-count in header right group — `fill: "#1c2128"`, `padding: [4, 10]`, `cornerRadius: 100`, `gap: 4`, `stroke: 1px #30363d`
- Live computed: `background: transparent`, `border: 1px solid #30363d`, `borderRadius: 100px`
- Bug location: `internal/web/ui/ds.css` — `.badge-neutral` or `#server-count` rule

## Out of Scope

- Server count pill padding (SPEC-BUG-076)
- Server count text content or icon

## Code Pointers

- `internal/web/ui/ds.css` — `.badge-neutral` rules (grep for `badge-neutral`)
- `internal/web/ui/index.html` — `<a id="server-count" class="badge badge-neutral">` (line ~25)

## Gap Protocol

- Research-acceptable gaps: whether `.badge-neutral` is used elsewhere and might need a scoped fix
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
