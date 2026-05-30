---
id: SPEC-BUG-131
template_version: 3
priority: 1
layer: 2
type: bugfix
status: in_progress
after: [SPEC-004, SPEC-BUG-045]
violates: [SPEC-004, UX-002]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Servers Tab Cards Reorder on Refresh

## Problem

On the Servers tab, server cards can change position while the page is open.
This makes the dashboard hard to follow during crashes, restarts, and polling
refreshes because a user cannot keep their eyes on one tile.

The Servers view is a monitoring surface. Tile position must be stable across
status refreshes unless the actual server set changes.

**Violated spec:** SPEC-004 (Phase 3: Multi-Server Dashboard)

**Violated criteria:** AC-3 requires real-time status updates for servers. Status
updates should update the card state in place, not reshuffle the whole grid.

**Violated spec:** UX-002 (Dashboard Design)

**Violated criteria:** The server dashboard design presents server cards as a
stable grid of server identity tiles. A card changing state should not move to a
different visual position.

## Reproduction

1. Start Shipyard with two or more configured child servers.
2. Open the Servers tab.
3. Leave the tab open while the polling loop or a `server_status` WebSocket
   event triggers repeated `GET /api/servers` refreshes.
4. Restart or stop one server, or wait for automatic status refreshes.
5. **Actual:** cards can appear in a different order between refreshes.
6. **Expected:** the built-in Shipyard card and all child server cards keep a
   deterministic order. Status, uptime, restart count, tool count, and action
   state update in place.

## Root Cause

Leave blank for the implementation pass.

## Requirements

- [ ] R1: `GET /api/servers` returns servers in a deterministic order across
  repeated calls while the server set is unchanged.
- [ ] R2: The built-in `shipyard` server keeps a stable, documented position.
- [ ] R3: Child servers keep a stable order that does not depend on Go map
  iteration.
- [ ] R4: Status changes, restart count changes, uptime changes, and tool count
  changes must not reorder cards.
- [ ] R5: If a server is added or removed, the remaining existing servers keep
  their relative order.
- [ ] R6: Existing config-order preservation behavior must not regress.

## Acceptance Criteria

- [ ] AC 1: Repeated calls to `GET /api/servers` return the same server-name
  sequence when the server set is unchanged.
- [ ] AC 2: A server status transition such as `online -> restarting -> online`
  does not change that server's index in the returned list.
- [ ] AC 3: The Servers tab renders cards in the API order and does not apply a
  second unstable client-side ordering.
- [ ] AC 4: The built-in `shipyard` card order is explicitly covered by tests.
- [ ] AC 5: Existing tests proving `Config.ServerOrder` preservation still pass.
- [ ] AC 6: Regression tests cover manager/API ordering with at least three
  child servers.
- [ ] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and
  `go test -race -count=1 -timeout 5m ./...` pass.

## Context

- User report: Servers tab order changes constantly, making it hard to follow
  what is happening.
- Servers UI refreshes via `loadServers()` in `internal/web/ui/index.html`.
- The server manager exposes `Servers()` from `internal/proxy/manager.go`.
- Config parsing already preserves JSON object key order in `Config.ServerOrder`
  and has coverage in `cmd/shipyard/config_test.go`.

## Out of Scope

- Adding manual drag-and-drop card reordering
- Adding sorting controls to the Servers tab
- Redesigning card contents or state visuals
- Changing server lifecycle semantics

## Code Pointers

- `internal/proxy/manager.go` - `Manager.Servers()`
- `internal/web/server.go` - `handleServers`
- `internal/web/ui/index.html` - `loadServers()` and `renderServerCards()`
- `cmd/shipyard/main.go` - config order and managed proxy registration path
- `cmd/shipyard/config_test.go` - existing `ServerOrder` tests
- `internal/web/server_test.go` - `/api/servers` response tests
- `internal/web/ui_layout_test.go` - Servers view structural tests

## Gap Protocol

- Research-acceptable gaps:
  - Whether stable order should be config order, registration order, or
    alphabetical fallback for dynamically discovered servers
  - Whether the built-in `shipyard` card should be first or last
- Stop-immediately gaps:
  - Any fix that stores ordering only in browser-local state while the API
    remains unstable
  - Any fix that breaks existing `Config.ServerOrder` behavior
- Max research subagents before stopping: 1
