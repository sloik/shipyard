---
id: SPEC-BUG-136
template_version: 3
priority: 2
layer: 2
type: bugfix
status: ready
after: [SPEC-BUG-134, SPEC-BUG-113]
violates: [SPEC-BUG-113, UX-002]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Long-Session UI Polling and DOM Budget

## Problem

Shipyard can start to lag after running for a long time. Source inspection shows
several UI paths that keep doing work even when the relevant view is not active
or when the DOM already contains many rows.

The dashboard needs explicit polling and DOM budgets so long-running sessions do
not degrade gradually.

**Violated spec:** SPEC-BUG-113 (Timeline Infinite Scroll)

**Violated criteria:** Infinite scroll should keep the traffic timeline usable;
it should not allow live WebSocket inserts and timestamp refreshes to grow the
active DOM without bound.

**Violated spec:** UX-002 (Dashboard Design)

**Violated criteria:** Operational surfaces should remain stable and responsive
during repeated monitoring use.

## Reproduction

1. Start Shipyard and leave the dashboard running for an extended session while
   MCP traffic flows.
2. Keep the app on Timeline or switch between Timeline, Tools, Servers, and
   History.
3. Observe periodic work in `internal/web/ui/index.html`:
   server polling every 2 seconds, live traffic row prepends, timestamp scans
   every 30 seconds, and full card/list rerenders.
4. **Actual:** UI work can continue to accumulate over time.
5. **Expected:** polling only runs for active surfaces, live DOM row counts are
   bounded, and expensive rerenders are skipped when data has not changed.

## Root Cause

Leave blank for the implementation pass.

## Requirements

- [ ] R1: Server status polling must only run while the Servers view is active,
  unless another visible surface explicitly needs it.
- [ ] R2: Polling timers must pause when the document is hidden and resume
  cleanly when visible.
- [ ] R3: Timeline live WebSocket inserts must enforce a bounded active DOM row
  budget.
- [ ] R4: Timestamp refresh must operate only on visible or bounded rows, not an
  ever-growing unbounded selector set.
- [ ] R5: Servers card rendering must skip full `innerHTML` replacement when the
  server list and status payload are unchanged.
- [ ] R6: Tools sidebar rendering must preserve selection and avoid full rerender
  on unrelated server/toggle events.
- [ ] R7: Frontend telemetry from SPEC-BUG-134 must report active row counts,
  render durations, and skipped-render counts.

## Acceptance Criteria

- [ ] AC 1: Tests or source-level regression checks prove `startServerStatePolling`
  is started/stopped based on active route and page visibility.
- [ ] AC 2: A timeline row budget exists and prevents active `.table-row`
  elements from growing without bound during live WebSocket traffic.
- [ ] AC 3: Timestamp refresh scans no more than the active row budget.
- [ ] AC 4: Servers render has a change-detection guard and tests covering the
  unchanged-payload no-rerender path.
- [ ] AC 5: Tools sidebar render has targeted update or skip behavior for
  unrelated toggle/server events.
- [ ] AC 6: Frontend telemetry exposes row counts and render durations for
  Timeline, Servers, and Tools.
- [ ] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and
  `go test -race -count=1 -timeout 5m ./...` pass.

## Context

- User report: app starts to lag after running for a long time.
- Server polling: `internal/web/ui/index.html` - `startServerStatePolling()`.
- Live traffic insertion: `internal/web/ui/index.html` - WebSocket
  `onmessage`.
- Timestamp refresh: `internal/web/ui/index.html` - 30-second interval near app
  initialization.
- Servers rendering: `internal/web/ui/index.html` - `loadServers()`,
  `renderServerCards()`.
- Tools rendering: `internal/web/ui/index.html` - `renderToolSidebar()`.

## Out of Scope

- Replacing the dashboard with a frontend framework
- Changing traffic capture semantics
- Removing live WebSocket updates
- Redesigning the visual layout

## Code Pointers

- `internal/web/ui/index.html` - polling, WebSocket, Timeline, Servers, Tools
- `internal/web/ui_layout_test.go` - source-level frontend behavior tests
- `internal/web/server_test.go` - API support tests if telemetry endpoints are
  needed

## Gap Protocol

- Research-acceptable gaps:
  - Exact initial DOM row budget after measuring current behavior
  - Whether row pruning should preserve the expanded detail row or collapse it
  - Whether document visibility pause should apply to all routes or only polling
- Stop-immediately gaps:
  - The fix drops live traffic data from storage instead of only pruning visible
    DOM
  - The fix makes the Timeline miss new live events while visible
  - The fix introduces duplicate timers or race detector failures
- Max research subagents before stopping: 1
