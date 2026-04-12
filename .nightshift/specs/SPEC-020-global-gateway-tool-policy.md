---
id: SPEC-020
template_version: 2
priority: 1
layer: 1
type: feature
status: done
after: [SPEC-019, SPEC-004]
prior_attempts: []
created: 2026-04-12
---

# Global Gateway Tool Policy in the Shared Shipyard Proxy

## Problem

`SPEC-019` added `shipyard-mcp`, which lets external MCP clients connect to one
Shipyard entry and discover namespaced child tools through the new Go/HTTP
Shipyard backend.

That is necessary, but not sufficient.

Shipyard is not just a dashboard or convenience index. **It is the proxy layer
between MCP clients and child MCP servers.** If multiple external clients
(Claude CLI, Codex, others) connect through separate bridge processes, then
tool enable/disable decisions cannot live in those bridge processes or in each
client’s local config. They must live in the shared Shipyard backend, where
every tool discovery and tool execution request passes through one source of
truth.

Without backend-owned gateway policy:

1. One client can still see or call a tool another client believes is disabled.
2. Each bridge rebuilds its own ad hoc catalog, so policy is not globally
   enforceable.
3. Shipyard stops being the authoritative proxy and becomes just a catalog
   adapter, which breaks the intended architecture.

The correct model is:

- external MCP clients talk to their own `shipyard-mcp` bridge processes
- every bridge talks to the same Shipyard backend
- Shipyard owns the global namespaced tool registry and enable/disable policy
- all clients see the same filtered catalog and receive the same enforcement

## Requirements

- [x] R1: Add a backend-owned gateway registry to the new Shipyard that treats
  namespaced child tools as a first-class shared resource in the proxy layer.
- [x] R2: Gateway policy state must live in Shipyard itself, not in
  `shipyard-mcp` bridge memory and not in per-client MCP config.
- [x] R3: Shipyard must support global enable/disable at two levels:
  - whole managed server
  - individual namespaced tool within a managed server
- [x] R4: The effective enablement rule must be deterministic:
  `server_enabled AND tool_enabled`.
- [x] R5: `shipyard-mcp` must consume the backend-owned filtered tool catalog
  instead of rebuilding its own unfiltered namespaced catalog directly from raw
  `/api/tools?server=...` calls.
- [x] R6: Shipyard must enforce policy on execution, not just discovery.
  A disabled server or disabled tool must be rejected by the backend even if a
  client tries to call it directly.
- [x] R7: Gateway policy must persist across Shipyard restarts.
- [x] R8: The backend must expose explicit HTTP endpoints for:
  - listing the global namespaced catalog
  - toggling server/tool enablement
  - optional inspection of effective enabled state
- [x] R9: The policy layer must coexist with Shipyard’s existing role as a
  traffic-inspecting stdio proxy for child MCPs. Do not bypass the proxy path.
- [x] R10: The design must remain safe for multiple simultaneous external MCP
  clients using separate bridge processes against one Shipyard backend.

## Acceptance Criteria

- [x] AC 1: Shipyard exposes a global gateway catalog API that returns
  namespaced tools in the format `{server}__{tool}` with effective enabled
  state.
- [x] AC 2: If server `lmstudio` is globally disabled in Shipyard, then
  `shipyard-mcp` no longer returns any `lmstudio__...` tools to any client.
- [x] AC 3: If only one namespaced tool is disabled, it disappears from
  `tools/list` for all clients while sibling tools from the same server remain.
- [x] AC 4: Calling a disabled namespaced tool is rejected by Shipyard even if a
  client bypasses a stale local view and attempts the call anyway.
- [x] AC 5: Calling a tool on a globally disabled server is rejected by Shipyard
  with a clear actionable error.
- [x] AC 6: Policy persists across Shipyard restart: a disabled server/tool
  remains disabled after the backend restarts.
- [x] AC 7: Two separate `shipyard-mcp` client sessions see the same filtered
  tool list after a policy change, without requiring client-specific config
  changes.
- [x] AC 8: Policy changes do not break Shipyard’s core proxy duties:
  server management, traffic capture, and tool execution continue to work for
  enabled tools.
- [x] AC 9: Automated tests cover catalog filtering, execution enforcement,
  persistence, and multi-client consistency.
- [x] AC 10: `go test ./...` passes.
- [x] AC 11: `go vet ./...` passes.
- [x] AC 12: `go build ./...` passes.

## Context

- Current bridge work:
  - `cmd/shipyard-mcp/main.go`
  - `SPEC-019-shipyard-mcp-bridge.md`
- Current backend APIs:
  - `internal/web/server.go`
  - `GET /api/servers`
  - `GET /api/tools?server=<name>`
  - `POST /api/tools/call`
- Current multi-server proxy lifecycle:
  - `internal/proxy/manager.go`
  - `SPEC-004-phase3-multi-server.md`
- Existing product direction:
  - Shipyard is the shared local proxy between clients and servers
  - multiple MCP clients may connect concurrently via separate bridge processes
- Important architectural constraint:
  - the bridge must remain thin
  - the backend must become the source of truth for gateway policy

## Alternatives Considered

- **Approach A (this spec): backend-owned global gateway policy**
  - Chosen because Shipyard is the shared proxy between clients and child MCPs.
  - Ensures all clients see and obey the same policy.

- **Approach B: keep policy inside each `shipyard-mcp` bridge**
  - Rejected because each client gets its own bridge process.
  - Produces fragmented state and no global enforcement.

- **Approach C: leave policy to each MCP client**
  - Rejected because it defeats Shipyard’s role as the controlling proxy layer.
  - One client could still call tools another thinks are disabled.

- **Approach D: disable tools only in the UI**
  - Rejected because UI-only state is not enforcement.
  - The proxy must block execution for disabled tools.

## Scenarios

1. User runs Shipyard and connects both Codex and Claude CLI through separate
   `shipyard-mcp` bridge processes → disables `lmstudio` globally in Shipyard →
   both clients lose `lmstudio__...` from `tools/list` on next discovery.

2. User disables only `filesystem__write_file` in Shipyard → both clients still
   see `filesystem__read_file` but not `filesystem__write_file`.

3. One client cached an older catalog and still tries to call a now-disabled
   tool → Shipyard rejects the call with a backend-owned disabled-tool error.

4. User restarts Shipyard → previously disabled servers/tools stay disabled →
   both clients reconnect and observe the same filtered catalog.

5. Shipyard manages multiple child MCP servers with overlapping raw tool names
   → the global registry remains namespaced and policy is applied to those
   namespaced identities.

## Exemplar

- **Source:** retired Swift gateway concept (`SPEC-002-gateway`) for the idea of
  central policy ownership
- **What to learn:** one source of truth for discovery, namespacing, and
  enablement
- **What NOT to copy:** Swift/socket transport, app-local gateway assumptions,
  or any design that predates the Go/HTTP Shipyard backend

## Out of Scope

- Per-client custom tool visibility rules
- Authenticated multi-user policy
- Remote/networked Shipyard deployments
- Replacing `shipyard-mcp` with native MCP-over-HTTP in this spec
- Reintroducing the retired `ShipyardBridge`

## Research Hints

- Files to study:
  - `internal/proxy/manager.go`
  - `internal/web/server.go`
  - `internal/web/server_test.go`
  - `cmd/shipyard-mcp/main.go`
  - `SPEC-019-shipyard-mcp-bridge.md`
- Patterns to look for:
  - persisted shared state in Go
  - catalog filtering before exposure
  - backend-side execution guards
- DevKB:
  - `DevKB/go.md`
  - `DevKB/architecture.md`

## Gap Protocol

- Research-acceptable gaps:
  - best persistence location for gateway policy state
  - exact API shape for the new gateway endpoints
  - whether filtered catalog should also expose disabled entries in admin/debug
    mode
- Stop-immediately gaps:
  - any design that leaves enforcement only in the bridge
  - any design that bypasses Shipyard’s proxy role and talks directly from
    clients to child MCP servers
  - ambiguity about whether execution rejection is mandatory
- Max research subagents before stopping: 0

## Notes for the Agent

- The key sentence for this spec is: **Shipyard is the proxy between clients and
  servers.**
- That means global policy belongs in Shipyard backend state, and every
  `tools/list` / `tools/call` path must flow through that state.
- The bridge should become thinner after this spec, not smarter.
