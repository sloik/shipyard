---
id: SPEC-044
template_version: 2
priority: 1
layer: 2
type: feature
status: done
after: [SPEC-019, SPEC-020]
prior_attempts: []
created: 2026-04-14
---

# Shipyard Self-Server — Expose Shipyard as a First-Class Server

## Problem

Shipyard manages child MCP servers and exposes a gateway MCP endpoint (`POST /mcp`) that
external clients (Claude CLI, Codex, other agents) can call. But Shipyard is **invisible to
those agents**: the servers list only shows child MCPs, and there is no way to discover or
call Shipyard's own management tools through the MCP protocol.

This creates two concrete gaps:

1. **Agents cannot manage Shipyard via MCP.** An agent that wants to check server health,
   restart a crashed child, or list available tools must use the HTTP API directly — there is
   no `shipyard__status` or `shipyard__restart` available as MCP tools through the gateway.

2. **Shipyard is invisible in the UI.** The Servers tab only shows child MCPs. A user (or
   agent browsing through the tool browser) has no entry point to see or interact with
   Shipyard's own capabilities.

The Swift version of Shipyard solved this explicitly (SPEC-006-shipyard-self-exposure):
Shipyard appeared as a permanent first entry in the Gateway sidebar, above child MCPs, with
its own tool catalog and per-tool enable/disable. The Go version has never implemented an
equivalent.

**User request:** Shipyard must appear in the Servers list and Tool Browser as a built-in
server, with management tools visible and callable via the MCP gateway, so other agents can
use Shipyard.

## What Already Works (do not rewrite)

- `POST /mcp` and `POST /mcp/{token}` — gateway MCP endpoint exists in `internal/web/server.go`
- `handleMCPPassthrough` / `auth.MCPHandler` — dispatch child server tool calls
- `GET /api/gateway/tools` — returns namespaced child tools (`{server}__{tool}`)
- `GET /api/servers` — returns child server list
- `cmd/shipyard-mcp/main.go` — bridge already has `shipyard_status` hardcoded
- Gateway policy (SPEC-020) — per-server and per-tool enable/disable, persistence

## Requirements

- [ ] R1: Define Shipyard's built-in management tool catalog as a static set of Go types in
  `internal/web/server.go` (or a new `internal/selfserver/` package if complexity warrants).
  Initial tools: `shipyard__status`, `shipyard__list_servers`, `shipyard__restart`,
  `shipyard__stop`. Tool names use the `shipyard__` prefix, consistent with the gateway
  namespacing convention.

- [ ] R2: `GET /api/servers` must prepend a synthetic Shipyard entry as the first item in
  the response. It must have `"name": "shipyard"`, `"status": "running"`, `"is_self": true`,
  `"tool_count": N` (count of management tools), and zero `restart_count` / `uptime_ms`
  fields. The `is_self` field signals the UI to suppress the gateway enable/disable toggle.

- [ ] R3: `GET /api/gateway/tools` must include Shipyard's management tools (`shipyard__*`)
  in the returned catalog. They must appear before child server tools in the list. They must
  be subject to per-tool gateway policy (enable/disable), but there must be no server-level
  gateway toggle for `shipyard` (it cannot be disabled wholesale, matching the Swift spec
  constraint).

- [ ] R4: `POST /api/tools/call` with `server=shipyard` must dispatch to the internal
  management tool handlers rather than proxying to a child process. Each management tool
  reads from the existing HTTP API internals (proxies, gateway store) without spawning a
  subprocess.

- [ ] R5: `POST /mcp` (both passthrough and auth-gated paths) must route `shipyard__*` tool
  calls to the same internal handlers as R4 — not forward them to a child proxy. The
  `handleMCPPassthrough` function's `extractPassthroughServer` logic (which reads `server`
  from params) must treat `"shipyard"` as the self-server and not look for it in `proxies`.

- [ ] R6: The Servers tab UI must render a permanent "Shipyard" card at the **top** of the
  server list, always, regardless of whether any child servers are configured. The card must
  show: green status indicator, "Shipyard" label, tool count (e.g., "4 tools"), version if
  available. It must NOT have a Gateway enable/disable toggle. It must be visually separated
  from child server cards (section divider or distinct header treatment per UX-002 design
  language).

- [ ] R7: The Tool Browser sidebar must list Shipyard's management tools under a "Shipyard"
  server group, displayed first before child server groups. Each tool must be selectable to
  show its schema form and allow direct execution (call the tool via `POST /api/tools/call`
  with `server=shipyard`). Per-tool enable/disable toggles in the sidebar follow the same
  gateway policy as child tools (R3).

- [ ] R8: The `cmd/shipyard-mcp` bridge's hardcoded `shipyard_status` tool in `listTools()`
  must be replaced or reconciled: the bridge should fetch Shipyard's management tools from
  `GET /api/gateway/tools` (which now includes `shipyard__*` entries) instead of maintaining
  a hardcoded inline definition. The tool count must stay consistent between the bridge and
  the server.

- [ ] R9: All four initial management tools must have working implementations:
  - `shipyard__status` — summary: reachability, N child servers, their names and statuses
  - `shipyard__list_servers` — full `GET /api/servers` payload (including self entry)
  - `shipyard__restart` — `POST /api/servers/{name}/restart` for a named child; error if
    `name` is `"shipyard"` (cannot restart self)
  - `shipyard__stop` — `POST /api/servers/{name}/stop` for a named child; same guard

## Acceptance Criteria

- [ ] AC 1: `GET /api/servers` returns a JSON array whose first element has
  `"name":"shipyard"`, `"status":"running"`, and `"is_self":true`.

- [ ] AC 2: `GET /api/gateway/tools` returns a list containing at least
  `shipyard__status`, `shipyard__list_servers`, `shipyard__restart`, and `shipyard__stop`
  as the first four entries, before any child tools.

- [ ] AC 3: `POST /mcp` with `{"method":"tools/list"}` returns a tools array that includes
  the four `shipyard__*` tools.

- [ ] AC 4: `POST /mcp` with `{"method":"tools/call","params":{"name":"shipyard__status"}}`
  returns a successful result with child server summary (does not error with "server not
  found" or similar).

- [ ] AC 5: `POST /mcp` with
  `{"method":"tools/call","params":{"name":"shipyard__restart","arguments":{"name":"lmstudio"}}}`
  triggers a restart of the `lmstudio` child server and returns a success result.

- [ ] AC 6: Calling `shipyard__restart` with `name=shipyard` returns an MCP error (cannot
  restart self), not a 5xx.

- [ ] AC 7: Disabling `shipyard__stop` via
  `POST /api/gateway/tools/shipyard/shipyard__stop/disable` causes it to disappear from
  `GET /api/gateway/tools` response (policy applied, same as child tools).

- [ ] AC 8: There is no `POST /api/gateway/servers/shipyard/disable` endpoint behaviour
  that disables the shipyard server — attempts to disable it at server level are rejected
  with a 400 or no-op (Shipyard cannot be disabled wholesale).

- [ ] AC 9: The Servers tab in the web UI shows a "Shipyard" card first, with green status,
  tool count, and no Gateway toggle. Child server cards appear below it.

- [ ] AC 10: The Tool Browser sidebar shows a "Shipyard" server group first with
  `shipyard__status`, `shipyard__list_servers`, `shipyard__restart`, `shipyard__stop` listed.
  Clicking a tool shows its schema form. Clicking Run submits the call and displays the
  result.

- [ ] AC 11: `cmd/shipyard-mcp` bridge no longer has a hardcoded `shipyard_status` tool
  definition — it reads `shipyard__*` tools from `GET /api/gateway/tools` instead.

- [ ] AC 12: `go test ./...` passes.
- [ ] AC 13: `go vet ./...` passes.
- [ ] AC 14: `go build ./...` passes.

## Context

**Key files to read before touching anything:**

Backend:
- `internal/web/server.go` — `handleServers`, `handleGatewayTools`, `handleToolCall`,
  `handleMCPPassthrough`, `ServerInfo`, `serverInfoResponse`, `gatewayCatalog`
- `internal/web/server_test.go` — test patterns, `mockProxyManager`, `newTestServer`
- `internal/gateway/` — gateway policy store (enable/disable persistence)
- `cmd/shipyard-mcp/main.go` — bridge `listTools()`, hardcoded `shipyard_status`, `callTool()`

Frontend (single HTML file, all changes go here):
- `internal/web/ui/index.html` — Servers tab rendering, Tool Browser sidebar rendering
- `internal/web/ui_layout_test.go` — existing layout tests (must stay green)
- `internal/web/ds.css`, `internal/web/ds.js` — design system (use DS classes only)

Design reference:
- `specs/UX-002-dashboard-design.pen` — Pencil source of truth for visual layout

Prior specs:
- `SPEC-019-shipyard-mcp-bridge.md` — MCP bridge background
- `SPEC-020-global-gateway-tool-policy.md` — gateway policy architecture
- `SPEC-006-shipyard-self-exposure.md` (Swift era, in Argo-wt-spec007) — UI behaviour reference

**Data model extension:** Add `IsSelf bool` to `ServerInfo` and `serverInfoResponse`:

```go
type ServerInfo struct {
    Name         string `json:"name"`
    Status       string `json:"status"`
    Command      string `json:"command,omitempty"`
    ToolCount    int    `json:"tool_count"`
    Uptime       int64  `json:"uptime_ms"`
    RestartCount int    `json:"restart_count"`
    ErrorMessage string `json:"error_message,omitempty"`
    IsSelf       bool   `json:"is_self,omitempty"`  // NEW — true for the Shipyard entry
}
```

**Synthetic server injection in handleServers:** Build the Shipyard entry inline:

```go
selfEntry := serverInfoResponse{
    ServerInfo: ServerInfo{
        Name:      "shipyard",
        Status:    "running",
        ToolCount: len(shipyardManagementTools),
        IsSelf:    true,
    },
    GatewayDisabled: false, // never disabled
}
result = append([]serverInfoResponse{selfEntry}, result...)
```

**Gateway catalog injection in gatewayCatalog:** Prepend static `shipyard__*` entries
before the child tool RPC calls. Gateway policy applies to these entries (tool-level only).
Server-level disable for `"shipyard"` must be a no-op or rejected in `handleGatewayServerDisable`.

**MCP routing — passthrough path:** In `handleMCPPassthrough`, before calling
`extractPassthroughServer`, check if the tool name starts with `shipyard__` and route to
the internal dispatcher. Do NOT forward to `proxies.SendRequest("shipyard", ...)` — that
server does not exist in the proxy manager.

**Auth-gated path:** Same guard in `auth.MCPHandler.handleToolsCall` — detect `shipyard__`
prefix, dispatch internally.

**Bridge reconciliation:** Remove the hardcoded `shipyard_status` entry from
`cmd/shipyard-mcp/main.go`'s `listTools()`. The bridge fetches from `GET /api/gateway/tools`
which now returns `shipyard__*` entries. The bridge's `callTool()` for `shipyard_status`
dispatch is no longer needed — `shipyard__status` calls flow through the regular
`{server}__{tool}` routing (with `server == "shipyard"` handled internally by the server).

**UI — Servers tab:** Find the servers list rendering in `index.html`. The JS that maps
`data.servers` to cards must handle `server.is_self === true`: render the Shipyard card
first without the gateway toggle, using the same DS card style as child cards but with a
visual separator below it.

**UI — Tool Browser:** The sidebar groups tools by server. A `shipyard` server group must
appear first. Its tools are rendered with the same row style as child tools. The form and
execution panels are identical — no special casing needed for tool invocation (it already
calls `POST /api/tools/call` with `server` and `tool` params).

## Alternatives Considered

- **Add a real proxy entry for "shipyard"** — rejected. The proxy manager manages child
  processes; adding a fake entry would require every proxy operation (`Restart`, `Stop`,
  `SendRequest`) to special-case it. Injecting at the API boundary is cleaner.

- **Separate `/api/self` endpoint** — rejected. Clients already consume `/api/servers`.
  Splitting adds a second fetch and more client-side logic for the same outcome.

- **Expose only through `/mcp`, not the UI** — rejected. The user explicitly wants the
  Servers tab and Tool Browser to show Shipyard. Agents that browse through the HTTP API
  also need it visible.

- **Keep bridge's hardcoded `shipyard_status`** — rejected. It's now a divergence: the
  bridge has one definition, the server has another. Single source of truth in the server.

## Scenarios

1. **Agent discovers Shipyard tools via MCP bridge** — agent calls `tools/list` through the
   bridge → receives `shipyard__status`, `shipyard__list_servers`, `shipyard__restart`,
   `shipyard__stop` plus all child tools. Agent calls `shipyard__status` → gets current
   server health summary.

2. **Agent restarts a crashed child via MCP** — agent calls `shipyard__restart` with
   `{"name": "lmstudio"}` → Shipyard restarts the child → returns `{"status":"restarting"}`.

3. **User opens the Servers tab** — Shipyard card appears first with green dot and "4 tools".
   Below it: child MCP cards with their gateway toggles. No toggle on the Shipyard card.

4. **User opens the Tool Browser** — Shipyard group appears first in the sidebar with its
   four tools listed. User clicks `shipyard__list_servers`, sees the schema form (one
   optional `name` filter field), clicks Run → response panel shows current server list.

5. **Admin disables `shipyard__stop` via gateway policy** — `shipyard__stop` disappears from
   `GET /api/gateway/tools` and from `tools/list` in the bridge. Calling it returns a
   disabled-tool error. Other `shipyard__*` tools remain unaffected.

6. **No child servers configured** — Servers tab shows only the Shipyard card. Tool Browser
   shows only the Shipyard group. No empty-state confusion.

## Exemplar

- **Source:** `Argo-wt-spec007/.../SPEC-006-shipyard-self-exposure.md` (Swift era)
- **What to learn:** permanent sidebar placement above children, no server-level disable,
  per-tool toggle reuses existing gateway controls, always-visible regardless of child count
- **What NOT to copy:** SwiftUI selection state (enum vs @State), Unix socket routing,
  UserDefaults persistence (Go uses the gateway.Store already)

## Out of Scope

- Adding more management tools beyond the initial four (metrics, traffic summary, etc.)
- Per-client tool visibility (all clients see the same Shipyard tools)
- Making the Shipyard card show real uptime or restart count (it's not a subprocess)
- Restart/Stop buttons on the Shipyard card in the Servers tab (those buttons apply to
  child servers; the card for Shipyard has none)
- Authenticated management tool access beyond the existing token auth path
- Any changes to the gateway policy persistence format

## Research Hints

Files to read:
- `internal/web/server.go` lines 109–118 (`ServerInfo`), 452–474 (`handleServers`),
  762–777 (`handleGatewayTools`), 1472–1516 (`handleMCPPassthrough`)
- `internal/auth/middleware.go` lines 199–256 (`handleToolsList`, `handleToolsCall`)
- `cmd/shipyard-mcp/main.go` lines 180–210 (`listTools`), 212–275 (`callTool`)
- `internal/gateway/` — `ServerEnabled`, `ToolEnabled`, `SetServerEnabled`
- `internal/web/ui/index.html` — grep for `servers` rendering and tool browser sidebar

Patterns to look for:
- How `gatewayCatalog` filters disabled tools — same logic applies to `shipyard__*`
- How `handleToolCall` dispatches to `proxies.SendRequest` — add early-exit for `shipyard`
- How the tool browser sidebar groups tools by server — Shipyard group is same shape

DevKB: `Argo Home/DevKB/architecture.md` § pipelines and proxy patterns

## Gap Protocol

Research-acceptable gaps:
- Exact JSON schema shape for each management tool's `inputSchema`
- Whether gateway policy table needs a schema migration for `"shipyard"` server entries
  (check `internal/gateway/` persistence format first)

Stop-immediately gaps:
- Any design that adds `"shipyard"` as a real entry in the proxy manager
- Any design that makes the bridge maintain its own separate management tool catalog
- Ambiguity about whether `POST /api/gateway/servers/shipyard/disable` should be rejected
  vs no-op (it must be rejected — server-level disable of Shipyard is not allowed)

Max research subagents before stopping: 0

## Notes for the Agent

- The synthetic Shipyard entry in `handleServers` is the single source of truth for the UI.
  Do not duplicate it in JS; let the `is_self` flag drive rendering decisions.
- The management tool dispatcher belongs in `internal/web/server.go` (or a small helper
  file in the same package). Keep it close to the HTTP handlers — it needs access to
  `s.proxies`, `s.gateway`, and `s.port`.
- Vanilla JS only in index.html. No async/await — use `.then()` chains.
- Design system classes only. Do not add custom CSS for the Shipyard card — reuse existing
  DS card, status dot, and section separator components.
- Run `go test ./...` after every non-trivial change. Do not stack multiple changes before
  checking for regressions.
