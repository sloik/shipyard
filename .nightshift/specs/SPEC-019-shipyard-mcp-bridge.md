---
id: SPEC-019
template_version: 2
priority: 1
layer: 1
type: feature
status: done
after: [SPEC-004, SPEC-017]
prior_attempts: []
created: 2026-04-12
---

# Shipyard MCP Bridge for External Clients

## Problem

The current Shipyard v2 app is a local HTTP/WebSocket service with a desktop
shell. It manages multiple MCP servers correctly and exposes useful HTTP APIs
such as `/api/servers`, `/api/tools`, and `/api/tools/call`, but MCP clients
like Claude CLI and Codex cannot connect to it directly because it does **not**
expose an MCP transport endpoint.

The retired macOS Shipyard solved this with `ShipyardBridge`: one MCP entry
point that clients connected to, while Shipyard handled discovery, namespacing,
routing, and lifecycle behind the scenes. That old design depended on a Swift
app and Unix socket protocol. It has now been removed and cannot be reused as
is.

This leaves a real gap:

1. The new Shipyard can manage multiple child MCP servers, but external MCP
   clients cannot use it as a single MCP endpoint.
2. Re-registering every child MCP separately in every client defeats the
   purpose of Shipyard as a central local tool hub.
3. Multiple clients may need access at the same time, so the replacement must
   work with concurrent independent MCP sessions without coupling them to a
   single stdio bridge process.

## Requirements

- [x] R1: Add a new `shipyard-mcp` bridge process that speaks MCP over `stdio`
  so MCP clients can register exactly one Shipyard entry.
- [x] R2: The bridge must treat the running Shipyard app as the source of truth
  and communicate with it through the existing local HTTP API, not through the
  removed Swift socket protocol.
- [x] R3: `tools/list` from the bridge must aggregate tools across all managed
  servers and expose them as namespaced MCP tools using the format
  `{server_name}__{tool_name}`.
- [x] R4: `tools/call` to a namespaced tool must route to the correct managed
  server through Shipyard and return the result in MCP-compatible form.
- [x] R5: The bridge must support multiple external clients concurrently by
  being stateless per connection and relying on the shared Shipyard backend for
  discovery and execution.
- [x] R6: If Shipyard is not running or unreachable, the bridge must fail
  clearly with actionable errors instead of hanging.
- [x] R7: The bridge must preserve request/response correlation correctly when a
  single MCP client issues multiple concurrent requests.
- [x] R8: The bridge must expose Shipyard management tools that are still useful
  to external clients, at minimum a health/status surface.
- [x] R9: The bridge implementation must be documented as the replacement for
  the removed `ShipyardBridge` binary and old gateway flow.

## Acceptance Criteria

- [x] AC 1: A user can register one `shipyard-mcp` stdio command in Claude CLI
  or Codex and successfully complete MCP initialization.
- [x] AC 2: `tools/list` returns aggregated namespaced tools for all currently
  managed servers when Shipyard has at least one running child MCP.
- [x] AC 3: A namespaced tool call such as `lmstudio__...` is routed to the
  correct Shipyard-managed server and returns the child MCP result.
- [x] AC 4: When Shipyard manages multiple child servers, duplicate raw tool
  names do not collide because the bridge exposes namespaced tool names.
- [x] AC 5: Two independent bridge client sessions can call `tools/list` and
  `tools/call` against the same running Shipyard instance without corrupting
  each other’s responses.
- [x] AC 6: If Shipyard is not reachable on its configured local API port, the
  bridge returns a clear error like `Shipyard is not running or unreachable`
  within 2 seconds.
- [x] AC 7: Concurrent requests from one client session maintain correct MCP
  request/response IDs and do not leak results across requests.
- [x] AC 8: The bridge has automated tests covering initialization, discovery,
  tool routing, Shipyard-unavailable failure, and concurrent request handling.
- [x] AC 9: Documentation shows how to register the new bridge in Claude CLI and
  Codex using one MCP entry.
- [x] AC 10: `go test ./...` passes.
- [x] AC 11: `go vet ./...` passes.
- [x] AC 12: `go build ./...` passes.

## Context

- Existing Shipyard HTTP API surface is in:
  - `internal/web/server.go`
  - `README.md` API section
- Existing multi-server contracts already exist:
  - `SPEC-004-phase3-multi-server.md`
  - `/api/servers`
  - `/api/tools?server=<name>`
  - `/api/tools/call`
- Desktop/Wails runtime work should remain separate from this bridge:
  - `SPEC-017-wails-desktop-app.md`
  - `SPEC-BUG-014`
  - `SPEC-BUG-015`
  - `SPEC-BUG-016`
- The old gateway design existed in the retired Swift Shipyard and is useful as
  conceptual reference only:
  - `Argo-wt-spec007/.../.nightshift/specs/SPEC-002-gateway.md`
  - `Argo-wt-spec007/.../.nightshift/specs/SPEC-006-shipyard-self-exposure.md`
- The old `ShipyardBridge` binary and config registrations have been removed.
- The new design must avoid any dependency on:
  - Unix socket protocol
  - Swift `SocketServer`
  - old `ShipyardBridgeLib`

## Alternatives Considered

- **Approach A (this spec): stdio MCP bridge over current HTTP API**
  - Chosen because it works with today’s Claude/Codex MCP registration model
    while reusing the new Shipyard backend as-is.
  - Keeps one shared Shipyard process and allows multiple clients to connect via
    separate bridge processes.

- **Approach B: make Shipyard itself expose MCP over HTTP**
  - Attractive long-term because it removes the extra bridge process.
  - Rejected for now because the current app does not expose `/mcp` or SSE, and
    Claude CLI/Codex registration on this machine is already proven with
    `stdio`-style MCP servers.

- **Approach C: restore old ShipyardBridge / Swift socket gateway**
  - Rejected because it belongs to the retired architecture and is already
    removed from active machine config.
  - Would duplicate logic that now lives in the Go/HTTP Shipyard.

- **Prior art:** old Swift gateway specs `SPEC-002-gateway` and
  `SPEC-006-shipyard-self-exposure` describe the user-facing goal, but not the
  correct transport for v2.

## Scenarios

1. User starts Shipyard with a config managing `lmstudio` and `filesystem` →
   Claude CLI connects only to `shipyard-mcp` → `tools/list` returns
   `lmstudio__...` and `filesystem__...` → Claude calls one tool from each
   successfully.

2. Codex and Claude CLI both connect to separate `shipyard-mcp` bridge
   processes while the same Shipyard instance is running → both discover the
   same tool catalog → both can call tools without interfering with each other.

3. User registers `shipyard-mcp` but Shipyard is not running → MCP init still
   succeeds → first `tools/list` or `tools/call` returns a fast, explicit
   “Shipyard unreachable” error instead of hanging.

4. User restarts a managed MCP server from Shipyard → a later `tools/list`
   reflects the new server/tool state without requiring each external client to
   track child MCP lifecycle directly.

5. Two managed servers expose the same raw tool name → the bridge publishes
   namespaced tools only, so the client sees no collision.

## Exemplar

- **Source:** retired Swift Shipyard gateway design in
  `Argo-wt-spec007/.../SPEC-002-gateway.md`
- **What to learn:** single-entry-point UX, namespaced tool catalog,
  clear lifecycle boundaries between client, bridge, and Shipyard backend
- **What NOT to copy:** Unix socket transport, Swift app coupling,
  direct reuse of `ShipyardBridge`

## Out of Scope

- Adding a native MCP `/mcp` HTTP endpoint directly to the main Shipyard app
- Reintroducing the old Swift socket server or `ShipyardBridge`
- Reworking Shipyard’s existing HTTP API surface unless a missing endpoint
  blocks the bridge
- Authentication/remote access for Shipyard
- UI changes beyond docs/help text needed for bridge setup

## Research Hints

- Files to study:
  - `internal/web/server.go`
  - `internal/web/server_test.go`
  - `internal/proxy/manager.go`
  - `README.md`
  - `cmd/shipyard/main.go`
- Old conceptual reference only:
  - `Argo-wt-spec007/.../SPEC-002-gateway.md`
  - `Argo-wt-spec007/.../SPEC-006-shipyard-self-exposure.md`
- Patterns to look for:
  - stdlib-first Go
  - request/response correlation in current proxy code
  - namespaced tool surfaces
- DevKB:
  - `DevKB/go.md`
  - `DevKB/architecture.md`

## Gap Protocol

- Research-acceptable gaps:
  - current `/api/tools/call` response contract details
  - best place for the new bridge binary/package in this repo
  - Claude/Codex MCP initialization expectations
- Stop-immediately gaps:
  - missing HTTP API needed to route a namespaced tool call
  - ambiguity about whether the bridge should expose only child tools or both
    child tools plus Shipyard management tools
  - any proposal that would silently reintroduce the retired Swift/socket path
- Max research subagents before stopping: 0

## Notes for the Agent

- The key product goal is unchanged from the old Shipyard: one MCP entry for
  external clients, many child MCPs behind it.
- The key architecture rule is new: Shipyard v2 is the shared HTTP backend.
  Do not rebuild a second orchestration stack in the bridge.
- Bias toward a bridge that can be run per client session while the Shipyard app
  remains the only long-lived shared process.
