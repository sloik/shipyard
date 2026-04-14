---
id: SPEC-BUG-042
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [SPEC-019]
prior_attempts: []
created: 2026-04-13
---

# Bridge returns zero gateway tools to Claude Code on startup

## Problem

When Claude Code launches ShipyardBridge as a stdio MCP server, the bridge connects to the Shipyard API but returns zero child MCP tools. Claude Code sees only `shipyard_status` (the hardcoded management tool) — none of the gateway-proxied tools from child servers (e.g., lmstudio's 13 tools) appear.

The Shipyard desktop app itself is healthy: the UI shows all servers and tools correctly. The bridge's `GET /api/gateway/tools` endpoint is the boundary where tools go missing.

**Violated spec:** SPEC-019 (Shipyard MCP Bridge)
**Violated criteria:** The bridge should expose all enabled gateway tools from child MCP servers as MCP tools to the host client.

## Reproduction

1. Start Shipyard with at least one child MCP configured (e.g., lmstudio). Wait for `schema baseline captured server=lmstudio tools=13` in the Shipyard log.
2. Launch ShipyardBridge via stdio:
   ```
   echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | /path/to/ShipyardBridge --api-base http://127.0.0.1:9417
   ```
3. Bridge logs: `[init] gateway refresh: no tools found, proceeding with management-only`
4. Send `tools/list` — response contains only `shipyard_status`
5. **Actual:** Zero gateway tools returned. Claude Code never registers `mcp__shipyard__*` tools (other than `shipyard_status`).
6. **Expected:** All enabled child tools appear in `tools/list` response, namespaced as `{server}__{tool}`.

**Confirming the API is live:** The Shipyard web dashboard loads the same data over `/api/tools?server=lmstudio` and shows all 13 tools.

## Root Cause

**Leave blank.** The implementation agent investigates and fills this in during the Nightshift run.

## Requirements

- [ ] When Shipyard has online child servers with tools, `tools/list` MUST include those tools
- [ ] The bridge must handle the case where child servers are still starting when the bridge initializes (not yet `"online"`)
- [ ] Once a child transitions to `"online"`, its tools must become available on the next `tools/list` call (the bridge must not cache a stale empty snapshot)
- [ ] The bridge must not break when Shipyard has zero child servers configured (management-only mode should still work)

## Acceptance Criteria

- [ ] AC 1: With Shipyard running and lmstudio online, `tools/list` returns lmstudio's tools namespaced as `lmstudio__<tool_name>`
- [ ] AC 2: If the bridge starts before a child server is online, a subsequent `tools/list` call (after the child comes online) returns the child's tools
- [ ] AC 3: `tools/call` with a gateway tool name (e.g., `lmstudio__lms_chat`) successfully proxies to the child
- [ ] AC 4: With zero child servers, `tools/list` returns only `shipyard_status` (no error)
- [ ] AC 5: The violated requirement from SPEC-019 now passes
- [ ] AC 6: No regressions — `go test ./...` passes, existing bridge tests still green

## Context

**Target files:**
- `cmd/shipyard-mcp/main.go` — bridge binary, `listTools()` (line 180), `fetchGatewayTools()` (line 297)
- `internal/web/server.go` — `handleGatewayTools()` (line 773), `gatewayCatalog()` (line 856)

**Test files:**
- `cmd/shipyard-mcp/main_test.go`
- `internal/web/server_test.go`

**Key observations for the investigating agent:**
- The bridge calls `GET /api/gateway/tools` — this endpoint filters by `srv.Status != "online"` (server.go:860) and silently skips servers whose `fetchRawTools()` fails (server.go:864)
- The bridge has `"listChanged": false` in its capabilities (main.go:159) — it does not notify clients when tools change
- The HTTP client has a 2-second timeout (main.go:41)
- The `[init] gateway refresh` log suggests the bridge does a one-time fetch at init, but the `listTools()` function is actually called on every `tools/list` RPC — verify whether caching is involved

## Out of Scope

- Protocol version mismatch (`2025-11-25` vs `2024-11-05`) — separate concern, not causing this bug
- Gateway policy filtering (enable/disable) — works correctly per existing tests
- Child MCP crash recovery — covered by SPEC-BUG-002
- UI-side tool display — works correctly
