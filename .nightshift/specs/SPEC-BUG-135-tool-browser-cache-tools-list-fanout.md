---
id: SPEC-BUG-135
template_version: 3
priority: 1
layer: 2
type: bugfix
status: in_progress
after: [SPEC-BUG-134, SPEC-009]
violates: [SPEC-004]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Tool Browser Avoids Repeated Live tools/list Fan-Out

## Problem

Opening the Tools tab can be slow because the frontend fans out to every child
server and the backend performs live `tools/list` RPCs for each server. After
the per-server loads finish, the UI also requests `/api/tools/conflicts`, whose
handler performs another live `tools/list` pass across online servers.

The gateway catalog path already reads schema snapshots to avoid short-lived
client timeout problems, but the direct Tools tab load still uses live RPCs and
duplicates work.

**Violated spec:** SPEC-004 (Phase 3: Multi-Server Dashboard)

**Violated criteria:** The Tool Browser should remain usable as server count and
tool count grow. Loading tool metadata should not repeatedly block on all child
servers when a snapshot cache exists.

## Reproduction

1. Start Shipyard with several managed child servers.
2. Open the Tools tab after the schema watcher has captured snapshots.
3. Observe requests from `loadTools()`:
   `/api/gateway/tools?include_disabled=1`, `/api/servers`, one
   `/api/tools?server=...` per child server, and `/api/tools/conflicts`.
4. **Actual:** tool load depends on live child RPC latency and repeats
   `tools/list` work.
5. **Expected:** the Tools tab uses a cached catalog/snapshot path for normal
   load, with a deliberate refresh path for live child RPC refreshes.

## Root Cause

Leave blank for the implementation pass.

## Requirements

- [ ] R1: Normal Tools tab load must not call live child `tools/list` for every
  online server when schema snapshots exist.
- [ ] R2: `/api/tools?server=...` must either use the latest snapshot by default
  or expose a clearly named cached endpoint used by the UI.
- [ ] R3: `/api/tools/conflicts` must compute conflicts from the same cached
  catalog/snapshot data used by the UI, not a second live RPC fan-out.
- [ ] R4: Provide an explicit force-refresh path for a user or test to request
  fresh live `tools/list` data when needed.
- [ ] R5: The UI must show stale/missing snapshot states clearly instead of
  silently presenting empty tools as if the server has no tools.
- [ ] R6: Tool enabled/disabled policy state from the gateway store must remain
  correct for cached tools.
- [ ] R7: Existing direct Shipyard self-tools behavior must not regress.

## Acceptance Criteria

- [ ] AC 1: With cached schema snapshots present, loading the Tools tab does not
  invoke child `tools/list` RPCs.
- [ ] AC 2: `/api/tools/conflicts` has regression coverage proving it does not
  invoke child `tools/list` RPCs when snapshots are present.
- [ ] AC 3: A force-refresh path exists and has tests proving it does call live
  `tools/list` and updates the snapshot/cache.
- [ ] AC 4: Missing snapshot state is represented in the API and UI with a
  non-empty status message or badge.
- [ ] AC 5: Gateway policy fields `enabled` and `server_enabled` remain present
  and accurate for cached tool entries.
- [ ] AC 6: Tool load performance telemetry from SPEC-BUG-134 distinguishes
  cached load from force-refresh load.
- [ ] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and
  `go test -race -count=1 -timeout 5m ./...` pass.

## Context

- User report: tools load slowly.
- UI load path: `internal/web/ui/index.html` - `loadTools()`.
- Direct API path: `internal/web/server.go` - `handleTools()`,
  `fetchToolsResult()`.
- Cached catalog path: `internal/web/server.go` - `gatewayCatalog()`.
- Conflict path: `internal/web/server.go` - `handleToolConflicts()`.
- Snapshot producer: `internal/proxy/manager.go` - `StartSchemaWatcher()`,
  `fetchToolsList()`.
- Snapshot storage: `internal/capture/store.go` - `SaveSnapshot()`,
  `GetLatestSnapshot()`.

## Out of Scope

- Changing MCP tool schemas
- Removing schema change detection
- Redesigning the Tools tab layout
- Caching tool execution results

## Code Pointers

- `internal/web/server.go` - tool API handlers and gateway catalog
- `internal/proxy/manager.go` - child RPC and schema watcher
- `internal/capture/store.go` - schema snapshot storage
- `internal/web/ui/index.html` - Tools tab load and sidebar render
- `internal/web/server_test.go` - `/api/tools`, gateway, and conflict tests
- `internal/proxy/manager_test.go` - child RPC timing and request tests
- `internal/web/ui_layout_test.go` - source-level UI tests

## Gap Protocol

- Research-acceptable gaps:
  - Whether `/api/tools?server=...` should default to cached or add a sibling
    endpoint such as `/api/tools/cache`
  - How long a snapshot can be considered fresh before warning the user
  - Whether force-refresh should be per-server or all-servers
- Stop-immediately gaps:
  - A cached path can expose stale tools without any freshness indication
  - The fix breaks Shipyard self-tools or gateway policy toggles
  - The fix hides live RPC failures during explicit refresh
- Max research subagents before stopping: 1
