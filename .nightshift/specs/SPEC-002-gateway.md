---
id: SPEC-002
priority: 1
layer: 1
type: feature
status: done
after: [SPEC-001]
prior_attempts: []
created: 2026-03-16
---

# Shipyard Gateway: Single MCP Entry Point

## Problem

Shipyard manages multiple local MCP (Model Context Protocol) servers running simultaneously on a developer's machine. Without a unified interface, Claude Desktop and Claude Code must:

1. Maintain separate connections to each MCP server individually
2. Manage tool discovery by directly querying each server (inefficient, scattered)
3. Handle per-tool enable/disable state with no centralized persistence or UI
4. Route tool calls directly to target MCPs (no aggregation, discovery, or namespacing)
5. Track MCP lifecycle (start/stop/crash) independently across multiple connections

This creates friction, scattered state management, and poor user visibility into the tool ecosystem. The ideal state: Claude connects to Shipyard once; Shipyard handles everything else.

## Requirements

### Gateway Registry & Discovery

- [x] GatewayRegistry component aggregates tools from all running child MCPs
  - Maintains a namespaced tool catalog: `{mcp-name}__{tool-name}`
  - Stores tool metadata: name, description, input_schema (see `Shipyard/Models/GatewayRegistry.swift`)
  - Indexed for O(1) lookup by namespaced tool name
  - Thread-safe via @MainActor isolation (concurrent reads, serialized writes)

- [x] Discovery protocol (`gateway_discover` socket method)
  - Calls `tools/list` on each running child MCP via MCPBridge
  - Aggregates results into GatewayRegistry
  - Returns full tool list with namespaced names and enabled state
  - Metadata includes: mcp_name, tool_name, description, input_schema, enabled, mcp_enabled

- [x] Discovery triggers (hot-reload)
  - On MCP process start
  - On MCP process stop
  - On manual refresh (user action in UI)
  - On Shipyard launch (initial discovery)

### Enable/Disable State Management

- [x] Dual-level enable toggles
  - MCP-level: entire MCP can be disabled (all tools become unavailable)
  - Tool-level: individual tool within enabled MCP can be disabled
  - Precedence: if MCP disabled → all tools disabled; otherwise tool state applies
  - Separate storage keys in UserDefaults:
    - `gateway.mcp.enabled.{mcp_name}` (boolean, defaults to true)
    - `gateway.tool.enabled.{mcp_name}.{tool_name}` (boolean, defaults to true)

- [x] State persistence via UserDefaults
  - All toggle state persists across app restarts
  - Writes are synchronous (no race conditions with app termination)
  - Defaults: MCPs enabled, all tools enabled (backward compatible)

### Tool Namespacing

- [x] Namespace format: `{mcp-name}__{tool_name}` (double underscore)
  - Matches Claude Code convention for delegated MCPs
  - Prevents tool name collisions across MCPs
  - Transparent to Claude (Claude sees namespaced name, Shipyard demultiplexes)

### Tool Forwarding & Routing

- [x] Tool call routing (`gateway_call` socket method)
  - Receives: namespaced tool name, arguments, request id
  - Validates:
    - Namespaced tool exists in registry
    - MCP is enabled
    - Tool is enabled
    - MCP process is running
  - Forwards to child MCP via MCPBridge (JSON-RPC on stdin, see `Shipyard/Services/MCPBridge.swift`)
  - Returns response to caller (stdout → ShipyardBridge → Claude)

- [x] Error handling for tool calls
  - `tool_unavailable` — namespaced tool not in registry or disabled
  - `mcp_not_running` — MCP process not currently running
  - `mcp_crashed` — MCP was running but exited unexpectedly
  - `timeout` — child MCP did not respond within 30 seconds
  - Include error message and suggestive context (e.g., "Enable MCP 'foo' to use this tool")

### ShipyardBridge Integration

- [x] ShipyardBridge exposes gateway to Claude
  - Listens on socket for Claude Desktop/Code connections
  - Implements socket protocol via SocketServer (`Shipyard/Services/SocketServer.swift`):
    - `gateway_discover` → list all tools with metadata
    - `gateway_call` → forward tool call to child MCP
    - `gateway_set_enabled` → toggle MCP or tool enabled state
  - No direct tool calls to MCPs; all go through gateway

- [x] Request/response correlation via request id
  - Each tool call has unique id (incremental)
  - Child MCP response includes matching id
  - MCPBridge correlates response to request, returns to sender
  - Handles out-of-order responses (child may respond in any order)

### Gateway UI (GatewayView)

- [x] Gateway tab (⌘2 keyboard shortcut, second tab in main window)
  - Shows all aggregated tools grouped by MCP (see `Shipyard/Views/GatewayView.swift`)
  - For each MCP: name, enabled/disabled toggle, status (running/stopped)
  - For each tool: namespaced name, description, enabled/disabled toggle
  - MCP-level toggle disables all child tools visually
  - Tool-level toggle only active if MCP is enabled
  - Real-time update on MCP start/stop/restart

- [x] Refresh button
  - Manual refresh of tool discovery
  - Useful if tool list changes in child MCP without restart (edge case)
  - Calls `gateway_discover` and updates GatewayRegistry

## Acceptance Criteria

### Discovery & Registry

- [x] AC 1: GatewayRegistry aggregates tools from all running MCPs without duplicates
- [x] AC 2: Tool names are namespaced as `{mcp-name}__{tool-name}` in registry
- [x] AC 3: `gateway_discover` returns all tools with correct metadata (name, description, input_schema, enabled)
- [x] AC 4: Discovery triggers automatically on MCP start, stop, and manual refresh
- [x] AC 5: GatewayRegistry is thread-safe (concurrent reads via @MainActor, no data corruption)

### Enable/Disable State

- [x] AC 6: MCP-level toggle persists to UserDefaults with key `gateway.mcp.enabled.{mcp-name}`
- [x] AC 7: Tool-level toggle persists to UserDefaults with key `gateway.tool.enabled.{mcp-name}.{tool-name}`
- [x] AC 8: Toggled state is restored on app restart
- [x] AC 9: Default state (all enabled) is applied if key doesn't exist
- [x] AC 10: MCP-level toggle disables all child tools (precedence logic: mcp_enabled AND tool_enabled)

### Tool Forwarding

- [x] AC 11: `gateway_call` routes to correct child MCP via MCPBridge
- [x] AC 12: Tool call returns child's response verbatim to caller
- [x] AC 13: Tool call timeout (30s) returns `timeout` error with suggestion
- [x] AC 14: Disabled MCP returns `mcp_not_running` or `tool_unavailable` error
- [x] AC 15: Disabled tool returns `tool_unavailable` error with suggestion to enable
- [x] AC 16: All errors include actionable error messages

### ShipyardBridge Integration

- [x] AC 17: ShipyardBridge socket accepts `gateway_discover`, `gateway_call`, `gateway_set_enabled` methods
- [x] AC 18: `gateway_discover` returns all aggregated tools
- [x] AC 19: `gateway_call` forwards tool call and returns response
- [x] AC 20: `gateway_set_enabled` updates toggle state and persists to UserDefaults
- [x] AC 21: Request/response correlation by id works correctly (out-of-order responses handled)

### UI (GatewayView)

- [x] AC 22: Gateway tab (⌘2) shows all MCPs grouped with tools
- [x] AC 23: MCP shows: name, status (running/stopped), enabled/disabled toggle
- [x] AC 24: Tool shows: namespaced name, description, enabled/disabled toggle
- [x] AC 25: MCP-level toggle disables all child tools visually (tool toggles disabled/grayed out)
- [x] AC 26: Tool-level toggle only active if MCP is enabled
- [x] AC 27: Toggling state in UI persists to UserDefaults and updates GatewayRegistry
- [x] AC 28: UI updates in real-time when MCP starts/stops/restarts
- [x] AC 29: Refresh button manually re-discovers tools

### Integration Tests

- [x] AC 30: End-to-end: Claude Code calls tool → Shipyard routes → child MCP executes → result returned
- [x] AC 31: Enable/disable state affects tool availability (correctly blocks unavailable tools)
- [x] AC 32: MCP crash is detected; tools become unavailable; error is returned to Claude
- [x] AC 33: Multiple concurrent tool calls are handled correctly (no race conditions)
- [x] AC 34: Tool call timeout is enforced; timeout error returned

## Context

### Key Swift Files

- **GatewayRegistry** (`Shipyard/Models/GatewayRegistry.swift`): @MainActor Observable class that aggregates tools from child MCPs, manages enable/disable state persisted to UserDefaults
- **GatewayView** (`Shipyard/Views/GatewayView.swift`): SwiftUI view showing aggregated tool catalog, MCP status, toggles for enable/disable, refresh button
- **SocketServer** (`Shipyard/Services/SocketServer.swift`): Listens on Unix socket, handles JSON-RPC dispatch for `gateway_discover`, `gateway_call`, `gateway_set_enabled`
- **MCPBridge** (`Shipyard/Services/MCPBridge.swift`): JSON-RPC 2.0 client that communicates with child MCP processes via stdio, correlates requests/responses by id, enforces 30s timeout

### Design Decisions

- **ADR 0003: Gateway Pattern** — Single aggregation point (Shipyard) instead of direct Claude-to-MCP connections. Rationale: scalability, resilience, centralized state, automatic discovery, prevents tool name collisions.
- **Namespacing Strategy** — Double underscore `{mcp-name}__{tool-name}` format. Prevents collisions, matches Claude Code convention, trivial demultiplexing.
- **Dual-Level Toggles** — MCP-level (disable entire server) and tool-level (disable specific tool). Supports both resource constraints and capability filtering with clear precedence logic.
- **Tool Call Timeout** — 30 seconds. Responsive for most operations (API calls, file I/O, GPU inference), prevents hanging indefinitely if child freezes.
- **Hot-Reload on MCP Lifecycle** — Automatic re-discovery on start/stop/restart. UX: user sees tool list update in real-time without manual refresh.
- **State Persistence** — UserDefaults (not SwiftData, not iCloud). Simplicity, per-machine scope, atomic synchronous writes prevent data loss on app termination.

### Tool Call Data Flow

**Scenario:** Claude Code calls `anthropic-files__read_file`

1. Claude Code sends JSON-RPC request to Shipyard socket:
   ```
   {
     "jsonrpc": "2.0",
     "id": "req-12345",
     "method": "tools/call",
     "params": {
       "name": "gateway_call",
       "arguments": {
         "tool": "anthropic-files__read_file",
         "path": "~/Documents/example.txt"
       }
     }
   }
   ```

2. ShipyardBridge (macOS app) receives on stdin, dispatches to SocketServer

3. SocketServer parses, routes "gateway_call" to GatewayRegistry

4. GatewayRegistry validates:
   - Tool "anthropic-files__read_file" exists? YES
   - MCP "anthropic-files" enabled? YES
   - Tool "read_file" enabled? YES
   - MCP process running? YES

5. GatewayRegistry calls MCPBridge.call(mcp_name: "anthropic-files", tool: "read_file", args: {...})

6. MCPBridge sends JSON-RPC to child's stdin:
   ```
   {
     "jsonrpc": "2.0",
     "id": "child-67890",
     "method": "tools/call",
     "params": {
       "name": "read_file",
       "arguments": { "path": "~/Documents/example.txt" }
     }
   }
   ```

7. Child MCP reads stdin, executes tool, writes response to stdout:
   ```
   {
     "jsonrpc": "2.0",
     "id": "child-67890",
     "result": {
       "content": "file contents here"
     }
   }
   ```

8. MCPBridge reads stdout, correlates response by id, returns to SocketServer

9. SocketServer returns to ShipyardBridge:
   ```
   {
     "jsonrpc": "2.0",
     "id": "req-12345",
     "result": {
       "content": "file contents here"
     }
   }
   ```

10. ShipyardBridge writes to stdout (Claude Code reads)

11. Claude Code receives result, displays to user

**Error case:** if MCP disabled or tool disabled, step 4 returns `tool_unavailable` error at step 9.

**Timeout case:** if child doesn't respond in 30s, MCPBridge returns `timeout` error.

## Scenarios

1. **Discover running MCPs**: User starts Shipyard while 3 MCPs (mac-runner, anthropic-files, llm-api) are already running → Shipyard auto-discovers all tools on launch → GatewayView shows all 3 MCPs with full tool lists → user can toggle each MCP/tool independently.

2. **MCP lifecycle**: User starts Shipyard → discovers 1 MCP → user stops the MCP process → SocketServer detects process termination → re-discovers (empty list for that MCP) → GatewayView grays out/removes tools, shows MCP status as "stopped" → user restarts MCP → tools reappear in real-time.

3. **Tool call with disabled MCP**: User disables "anthropic-files" MCP in GatewayView → toggle persists to UserDefaults → Claude Code tries to call `anthropic-files__read_file` → SocketServer validates in GatewayRegistry → finds MCP disabled → returns `mcp_not_running` error to Claude Code with message "Enable MCP 'anthropic-files' to use this tool".

4. **Tool call with disabled tool**: User enables "anthropic-files" MCP but disables "delete_file" tool → Claude Code calls `anthropic-files__read_file` → succeeds (tool enabled) → Claude Code calls `anthropic-files__delete_file` → SocketServer returns `tool_unavailable` error "Tool 'delete_file' is disabled. Enable it in Gateway tab."

5. **Tool call timeout**: Child MCP (mac-runner) hangs processing `run_command` → MCPBridge waits 30s for response → timeout expires → MCPBridge returns `timeout` error to SocketServer → Claude Code receives "Tool 'run_command' did not respond within 30 seconds. Try again or restart MCP 'mac-runner'."

6. **Manual refresh**: User is in Gateway tab → clicks Refresh button → SocketServer calls gateway_discover → MCPBridge re-queries all running MCPs for tool lists → GatewayRegistry updates → GatewayView re-renders with latest tool list (handles edge case where child MCP loaded new plugin without restart).

## Out of Scope

- Tool search/filter in GatewayView (post-MVP)
- Tool usage analytics (post-MVP)
- Tool metadata browser detail pane (post-MVP)
- Bulk enable/disable (post-MVP)
- Export/import gateway state (post-MVP)
- Tool groups/categories (post-MVP)
- Configurable timeout (post-MVP)
- Webhook-based MCP discovery (static local MCPs only)

## Notes for the Agent

### Implementation is Complete

This spec documents a fully implemented, shipped feature (Phases 7-8 complete as of Session 46+). All code is in place:

- **GatewayRegistry** — manages tool aggregation, enable/disable state, UserDefaults persistence
- **GatewayView** — SwiftUI tab showing MCPs and tools with toggles
- **SocketServer** — JSON-RPC dispatch for gateway methods
- **MCPBridge** — async/await JSON-RPC 2.0 client with timeout enforcement

### Key Implementation Notes

1. **@MainActor isolation** in GatewayRegistry prevents race conditions without locks
2. **Thread-safe request correlation** in MCPBridge uses incremental IDs; pending requests stored in nonisolated(unsafe) dict with CheckedContinuation
3. **UserDefaults keys** follow pattern `gateway.mcp.enabled.{mcp_name}` (MCP-level) and `gateway.tool.enabled.{mcp_name}.{tool_name}` (tool-level)
4. **Precedence logic** — tool availability = mcp_enabled AND tool_enabled (checked in SocketServer validation)
5. **Hot-reload** — GatewayRegistry observes ProcessManager/MCPRegistry changes via .onChange, triggers re-discovery
6. **Error specificity** — four distinct error categories (tool_unavailable, mcp_not_running, mcp_crashed, timeout) with actionable messages

### Testing Approach

- Unit tests on GatewayRegistry: add/remove tools, toggle state, precedence logic
- Unit tests on MCPBridge: JSON-RPC encoding, timeout handling, response correlation
- Integration tests: end-to-end tool call flow, enable/disable state effects, MCP lifecycle detection
- Manual T2 tests (Session 46+): Claude Code integration with real MCPs

### Known Limitations (Documented)

- Tool schema changes require manual refresh (not auto-detected mid-session)
- Tool list changes in child MCP without restart visible only on manual refresh (timeout risk on discovery if child adds slow tool)
- Timeout hardcoded to 30s (considered post-MVP configurability)

### Metrics from Phase 1-8

- Discovery latency: <5s for 10+ MCPs (verified in testing)
- Tool call forwarding overhead: <100ms RTT (JSON-RPC serialization + stdio roundtrip)
- Memory footprint: <10MB for 100 tools (acceptable for UserDefaults-backed state)
