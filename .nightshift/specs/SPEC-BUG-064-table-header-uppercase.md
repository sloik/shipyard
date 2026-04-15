---
id: SPEC-BUG-064
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

# Table header text is uppercase via CSS, design shows title-case

## Problem

The `.table-header > *` CSS rule includes `text-transform: uppercase`, rendering all header labels as "TIME", "DIR", "SERVER", etc. The UX-002 design shows title-case labels: "Time", "Dir", "Server", "Method", "Status", "Latency".

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header-row node (`iwPKi`) — text content is title-case: `"Time"`, `"Dir"`, `"Server"`, `"Method"`, `"Status"`, `"Latency"`. No text-transform property present in the design.

## Reproduction

1. Open the Timeline tab in Shipyard UI
2. Look at the table header labels
3. **Actual:** Labels show as "TIME", "DIR", "SERVER", etc. (all uppercase)
4. **Expected:** Labels show as "Time", "Dir", "Server", etc. (title-case, matching HTML source)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Remove `text-transform: uppercase` from `.table-header > *`
- [ ] R2: Verify HTML source has correct title-case labels (no need to change HTML if already title-case)

## Acceptance Criteria

- [ ] AC 1: `.table-header > *` in `ds.css` does NOT include `text-transform: uppercase`
- [ ] AC 2: Timeline table headers show "Time", "Dir", "Server", "Method", "Status", "Latency"
- [ ] AC 3: History and other table headers also show their original case
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `iwPKi` (header-row) — child text nodes use title-case content with no text-transform
- Bug location: `internal/web/ui/ds.css`, `.table-header > *` rule (line ~996)
- Note: The Tokens table headers are written as ALL CAPS in HTML ("NAME", "CREATED", etc.) — removing text-transform won't affect them since they're already uppercase in source

## Out of Scope

- Table header letter-spacing changes
- Tokens table header text (already uppercase in HTML source)
- Table header color (SPEC-BUG-056)

## Code Pointers

- `internal/web/ui/ds.css` — `.table-header > *` (line ~996, `text-transform: uppercase` at line ~1001)

## Gap Protocol

- Research-acceptable gaps: verify Tokens table HTML header text is already uppercase
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
