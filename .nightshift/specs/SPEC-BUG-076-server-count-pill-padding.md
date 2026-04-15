---
id: SPEC-BUG-076
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

# Server count pill padding is 1px 8px, design specifies 4px 10px

## Problem

The `#server-count` badge has `padding: 1px 8px`. The UX-002 design specifies `padding: [4, 10]` for the server-count pill, making it slightly larger and more readable.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Server-count node in Header/AppBar right group — `padding: [4, 10]`.

## Reproduction

1. Open any page in Shipyard UI
2. Inspect the server count pill padding
3. **Actual:** padding is 1px 8px
4. **Expected:** padding should be 4px 10px

## Root Cause

`.badge` base rule in `ds.css` had `padding: 1px 8px`. Changed to `padding: 4px 10px` per UX-002 spec. All badge variants inherit this, which is correct — all badges benefit from the updated sizing.

## Requirements

- [ ] R1: Server count pill has `padding: 4px 10px`

## Acceptance Criteria

- [ ] AC 1: `#server-count` renders with `padding: 4px 10px`
- [ ] AC 2: Pill still fits within the header height (48px)
- [ ] AC 3: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, server-count — `padding: [4, 10]`
- Live computed: `padding: 1px 8px`
- Bug location: `internal/web/ui/ds.css` — `.badge` or `.badge-neutral` padding rule

## Out of Scope

- Server count pill background (SPEC-BUG-075)
- Server count pill gap or border

## Code Pointers

- `internal/web/ui/ds.css` — `.badge` base rule (grep for `.badge {`)

## Gap Protocol

- Research-acceptable gaps: whether changing badge padding affects other badges
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
