---
id: SPEC-006-003
template_version: 2
priority: 3
layer: 2
type: feature
status: done
parent: SPEC-006
after: [SPEC-004]
nfrs: [SPEC-NFR-001]
prior_attempts: []
created: 2026-04-14
---

# Schema Change Detection

## Problem

MCP servers can change their `tools/list` response at any time — adding, removing, or
modifying tools. When this happens silently, downstream consumers (LLM agents, scripts,
CI pipelines) break without warning. Developers using Shipyard have no way to know that
a server's schema changed until something fails. Proactive detection and alerting would
catch these changes immediately.

## Requirements

- [ ] R1: Shipyard periodically polls `tools/list` for each connected server at a
  configurable interval (default 60 seconds).
- [ ] R2: When a schema change is detected, a dismissible alert banner appears on the
  dashboard showing which server changed, what changed, and when.
- [ ] R3: Change history is persisted in a new SQLite table with full before/after
  schema snapshots.
- [ ] R4: A change history sidebar shows a chronological list of all detected changes
  with timestamps and badges (+N added, -N removed, ~N modified).
- [ ] R5: A diff detail view shows added tools (green, with full schema), removed tools
  (red), and modified parameters (highlighted).
- [ ] R6: Users can acknowledge a change to dismiss the alert banner.
- [ ] R7: Schema change events are pushed to the dashboard via WebSocket in real-time.

## Acceptance Criteria

- [ ] AC 1: Shipyard polls `tools/list` for each connected server at the configured
  interval (default 60s); polling interval is configurable via server config.
- [ ] AC 2: When tools are added, removed, or modified, a warning banner appears at the
  top of the dashboard with the server name, change summary, and timestamp.
- [ ] AC 3: `GET /api/schema/changes` returns a list of all schema change events with
  timestamps, server name, and change summary (+N/-N/~N).
- [ ] AC 4: `GET /api/schema/changes/{id}` returns the full diff for a change event:
  added tools (with schema), removed tools, and modified parameters.
- [ ] AC 5: Schema change events persist in SQLite; `GET /api/schema/changes` returns
  events from previous Shipyard sessions after restart.
- [ ] AC 6: The change history sidebar lists events chronologically with color-coded
  badges: green for additions, red for removals, yellow for modifications.
- [ ] AC 7: Clicking a change event in the sidebar shows the diff detail view with
  added tools in green, removed tools in red, and modified parameters highlighted.
- [ ] AC 8: `POST /api/schema/changes/{id}/acknowledge` marks the change as acknowledged;
  the alert banner for that change is dismissed.
- [ ] AC 9: Schema change events are pushed via WebSocket — the dashboard updates without
  polling or page refresh.
- [ ] AC 10: `GET /api/schema/current/{server}` returns the current cached schema for a
  server.
- [ ] AC 11: `go test -race -count=1 -timeout 5m ./...` passes with zero race warnings.
- [ ] AC 12: `go vet ./...` passes clean.
- [ ] AC 13: `go build ./...` compiles without errors.

## API Endpoints

- `GET /api/schema/changes` — list schema change events
- `GET /api/schema/changes/{id}` — get change detail with diff
- `POST /api/schema/changes/{id}/acknowledge` — acknowledge a change
- `GET /api/schema/current/{server}` — get current schema for a server

## Context

### Target files

- `internal/schema/poller.go` — new: periodic `tools/list` polling, diff comparison,
  change event generation
- `internal/schema/diff.go` — new: schema diff algorithm (compare two `tools/list`
  responses, produce added/removed/modified sets)
- `internal/schema/store.go` — new: SQLite table for schema snapshots and change events
- `internal/schema/handler.go` — new: HTTP handlers for schema API endpoints
- `internal/schema/ws.go` — new: WebSocket push for schema change events
- `internal/web/ui/index.html` — add Schema tab (or sub-nav), alert banner component,
  change history sidebar, diff detail view
- `internal/web/routes.go` — register schema API routes and WebSocket endpoint

### Test files

- `internal/schema/diff_test.go` — diff algorithm tests (added, removed, modified tools)
- `internal/schema/store_test.go` — SQLite CRUD tests for schema snapshots and events
- `internal/schema/poller_test.go` — polling interval and change detection tests
- `internal/schema/handler_test.go` — HTTP handler tests
- `internal/web/ui_layout_test.go` — UI alert banner and schema tab presence

### Design reference

`UX-002-dashboard-design.pen` → "Phase 4 — Schema Changes" screen:
- Header with nav tabs
- SchemaAlertBanner: warning banner at top of dashboard when schema change detected,
  showing server name, change summary, dismiss/acknowledge button
- SchemaContent: two-panel layout — change history sidebar (left) with chronological
  list of events and badges, diff detail view (right) showing added/removed/modified
  tools with color coding

### Schema diff algorithm

Compare two `tools/list` JSON responses:
- **Added**: tool name present in new but not old
- **Removed**: tool name present in old but not new
- **Modified**: tool name in both but `inputSchema` or `description` differs

Store both the old and new full schema snapshots so diffs can be recomputed.

## Scenarios

1. Developer has Shipyard proxying "my-server" → server adds a new tool "analyze_data"
   → within 60s, alert banner appears: "Schema changed: my-server — +1 tool added" →
   developer clicks banner → sees diff showing "analyze_data" with full schema in green.
2. Developer opens Schema tab → sees change history sidebar with 3 events → clicks the
   oldest event → sees diff showing 2 tools were removed and 1 was modified → acknowledges
   the event → alert badge count decreases.
3. Server removes a tool → WebSocket pushes event → dashboard shows alert without page
   refresh → developer is on Traffic tab but sees the banner immediately.
4. Developer restarts Shipyard → opens Schema tab → sees all previous change events
   intact → current schema matches last polled state.
5. Developer has 3 servers connected → each is polled independently → change in server A
   does not affect server B's schema state.

## Out of Scope

- Alerting integrations (email, Slack, webhooks)
- Schema versioning or rollback
- Automatic re-polling after acknowledge (continue normal interval)
- Schema comparison across different servers
- Schema export/import

## Research Hints

- Files to study: `internal/capture/store.go` (SQLite table creation pattern),
  `internal/web/routes.go` (route and WebSocket registration if any exist),
  `internal/proxy/proxy.go` (how `tools/list` calls are made to child servers)
- Patterns to look for: existing WebSocket usage in the codebase, how `tools/list`
  responses are parsed, JSON-RPC message structure for `tools/list`
- DevKB: DevKB/go.md, DevKB/javascript.md

## Gap Protocol

- Research-acceptable gaps: existing WebSocket patterns in the codebase, exact
  `tools/list` response JSON structure from connected servers
- Stop-immediately gaps: no existing mechanism to call `tools/list` on a server
  (would need proxy-level changes outside this spec's scope), unclear diff granularity
  requirements
- Max research subagents before stopping: 3

---

## Notes for the Agent

- **Vanilla JS only**: use `var` declarations, `.then()` callbacks — no `async/await`,
  no `let/const`. This matches the project convention in all existing UI code.
- **WebSocket for real-time push**: use Go's `golang.org/x/net/websocket` or
  `nhooyr.io/websocket` if already in the module, otherwise use `net/http` upgrade
  pattern. Check existing WebSocket usage in the codebase first.
- **New SQLite table**: `schema_snapshots` table storing server name, timestamp, full
  `tools/list` JSON, and a change event reference. Follow the pattern in
  `internal/capture/store.go`.
- **Diff algorithm**: keep it simple — compare tool names for added/removed, then deep
  compare `inputSchema` JSON for modified. Use `reflect.DeepEqual` or JSON string
  comparison. No need for a sophisticated diff library.
- **Alert banner**: the banner should be visible on ALL tabs, not just the Schema tab.
  It sits at the top of the dashboard layout. Use DS alert/banner component if available.
- **Polling goroutine**: start one goroutine per connected server. Use `context.Context`
  for cancellation on shutdown. Ensure thread-safe access to the schema store (the NFR
  requires zero data races under `-race`).
- **Schema tab**: this is tab 7 in the main nav, or accessible as a sub-navigation from
  Servers view. Follow the design reference for exact placement.
- **Acknowledge state**: store in SQLite alongside the change event. Acknowledged events
  still appear in history but don't trigger the alert banner.
