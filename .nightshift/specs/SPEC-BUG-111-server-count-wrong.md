---
id: SPEC-BUG-111
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Server count shows 1 but 2 servers are running

## Problem

The Servers tab label shows "Servers (1)" and the stats bar shows "1 online", but the server grid actually renders 2 server cards (Shipyard and lmstudio). The count is inaccurate — it appears to exclude the built-in Shipyard server from the count.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Server count in tab label and stats bar must reflect the actual number of configured/connected servers.

## Reproduction

1. With Shipyard and lmstudio MCPs running, navigate to the Servers tab
2. **Actual:** Tab reads "Servers (1)", stats bar says "1 online", but 2 cards are visible (Shipyard + lmstudio)
3. **Expected:** Tab reads "Servers (2)", stats bar says "2 online"

## Root Cause

In `loadServers()`, `serverCount` was set to `childServers.length` — a filtered list that excluded entries where `s.is_self === true` (the built-in Shipyard gateway server). The stats loop similarly skipped self-entries entirely, so the online count also omitted Shipyard. The SSE `server_status` handler had the same filter. Since the Shipyard built-in card is always rendered in the grid, the displayed count (1) was always one less than the visible cards (2).

## Requirements

- [x] R1: Server count includes the built-in Shipyard server
- [x] R2: Tab label count matches the number of server cards rendered
- [x] R3: Stats bar "N online" count matches the number of online servers

## Acceptance Criteria

- [x] AC 1: With Shipyard + 1 external MCP, tab shows "Servers (2)"
- [x] AC 2: Stats bar shows "2 online" when both are running
- [x] AC 3: If an external MCP stops, counts update to reflect (e.g., "Servers (2)", "1 online, 1 crashed")
- [x] AC 4: `go build ./...` passes

## Context

- Live: `#server-count-label` shows "(1)", stats bar says "1 online", but `#servers-grid` has 2 `.server-card` children
- The Shipyard built-in card has custom inline styles (separate bug BUG-115) — may also be excluded from count logic
- JS updates the count via `serverCountEl` references (index.html lines ~3108, ~4138)

## Out of Scope

- Server card styling (BUG-115)
- Tab label format (BUG-100 already handled "Servers (N)" format)

## Code Pointers

- `internal/web/ui/index.html` — JS that computes server count (look for `serverCount` variable)
- Server list API endpoint that provides the data

## Gap Protocol

- Research-acceptable gaps: exact API endpoint and response format
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
