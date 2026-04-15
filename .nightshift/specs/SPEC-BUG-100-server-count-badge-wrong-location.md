---
id: SPEC-BUG-100
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

# Server count is a header badge, design puts count in the Servers tab label

## Problem

The live UI shows a separate `badge badge-neutral` pill ("1 server") in the header's right area next to the WS indicator. The UX-002 design does not have this badge — instead, the server count is part of the Servers tab label text: `"Servers (4)"` (node `jRwzp`).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Server count should appear as "(N)" suffix in the Servers tab label, not as a separate header badge.

## Reproduction

1. Open any tab, look at the header right area
2. **Actual:** "1 server" badge pill next to WS indicator and settings icon
3. **Expected:** No separate badge; Servers tab label reads "Servers (N)" where N is the dynamic count

## Root Cause

(Agent fills in during run.)

## Requirements

- [x] R1: Remove the `#server-count` badge from the header right area
- [x] R2: Update the Servers tab label to include dynamic count: "Servers (N)"

## Acceptance Criteria

- [x] AC 1: No server-count badge in the header
- [x] AC 2: Servers tab label dynamically shows "Servers (N)"
- [x] AC 3: Count updates when servers connect/disconnect
- [x] AC 4: `go build ./...` passes

## Context

- Design: Servers tab label node `jRwzp`: `content: "Servers (4)"`, inside tab `qUXmt`
- Live: `#server-count` badge at line 29 of index.html, updated by JS at lines ~3108 and ~4138
- Design header right area only has: WS indicator + settings icon

## Out of Scope

- Server count accuracy (functional, not visual)
- WS indicator styling

## Code Pointers

- `internal/web/ui/index.html` — `#server-count` badge (line ~29), Servers tab link (line ~24)
- JS: `serverCountEl.textContent = serverCount + ' server'...` (lines ~3108, ~4138)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
