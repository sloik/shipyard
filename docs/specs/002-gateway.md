# Spec: Shipyard Gateway Feature
**Status:** Accepted (Fully Implemented, Phase 7-8)
**Author:** AI assistant
**Date:** 2026-03-16
**Version:** 1.0

---

## Problem Statement

Shipyard manages multiple local MCP (Model Context Protocol) servers running simultaneously on a developer's machine. Without a unified interface, Claude Desktop and Claude Code must:

1. **Maintain separate connections** to each MCP server individually
2. **Manage tool discovery** by directly querying each server (inefficient, scattered)
3. **Handle per-tool enable/disable state** with no centralized persistence or UI
4. **Route tool calls** directly to target MCPs (no aggregation, discovery, or namespacing)
5. **Track MCP lifecycle** (start/stop/crash) independently across multiple connections

This creates **friction, scattered state management, and poor user visibility** into the tool ecosystem. The ideal state: **Claude connects to Shipyard once; Shipyard handles everything else** (ADR 0003).

---

## Vision Statement

**Shipyard Gateway acts as a single aggregation point and traffic router for all child MCP servers.** Claude Desktop/Code connects to Shipyard; Shipyard:

- **Discovers** all tools from all running MCPs
- **Aggregates & persists** tool metadata, enable/disable state, and grouping
- **Routes** tool calls transparently to the correct MCP
- **Hot-reloads** on MCP start/stop/restart
- **Provides UI visibility** into the tool ecosystem with granular control

**Result:** Single connection, unified discovery, transparent routing, persistent state, and full visibility.

---

## Requirements

### Must Have (MVP)

#### Gateway Registry & Discovery

1. **GatewayRegistry** component aggregates tools from all running child MCPs
   - Maintains a namespaced tool catalog: `{mcp-name}__{tool-name}`
   - Stores tool metadata: name, description, input_schema
   - Indexed for O(1) lookup by namespaced tool name
   - Thread-safe (concurrent reads, serialized writes)

2. **Discovery protocol** (`gateway_discover` socket method)
   - Calls `tools/list` on each running child MCP via MCPBridge
   - Aggregates results into GatewayRegistry
   - Returns full tool list with namespaced names and enabled state
   - Metadata includes: mcp_name, tool_name, description, input_schema, enabled, mcp_enabled

3. **Discovery triggers** (hot-reload)
   - On MCP process start
   - On MCP process stop
   - On manual refresh (user action in UI)
   - On Shipyard launch (initial discovery)

#### Enable/Disable State Management

4. **Dual-level enable toggles**
   - **MCP-level:** entire MCP can be disabled (all tools become unavailable)
   - **Tool-level:** individual tool within enabled MCP can be disabled
   - Precedence: if MCP disabled → all tools disabled; otherwise tool state applies
   - Separate storage keys in UserDefaults:
     - `shipyard.mcp.{mcp_name}.enabled` (boolean, defaults to true)
     - `shipyard.tool.{mcp_name}.{tool_name}.enabled` (boolean, defaults to true)

5. **State persistence** via UserDefaults
   - All toggle state persists across app restarts
   - Writes are synchronous (no race conditions with app termination)
   - Defaults: MCPs enabled, all tools enabled (backward compatible)

#### Tool Namespacing

6. **Namespace format:** `{mcp-name}__{tool_name}` (double underscore)
   - Matches Claude Code convention for delegated MCPs
   - Prevents tool name collisions across MCPs
   - Transparent to Claude (Claude sees namespaced name, Shipyard demultiplexes)

#### Tool Forwarding & Routing

7. **Tool call routing** (`gateway_call` socket method)
   - Receives: namespaced tool name, arguments, request id
   - Validates:
     - Namespaced tool exists in registry
     - MCP is enabled
     - Tool is enabled
     - MCP process is running
   - Forwards to child MCP via MCPBridge (JSON-RPC on stdin)
   - Returns response to caller (stdout → ShipyardBridge → Claude)

8. **Error handling** for tool calls
   - `tool_unavailable` — namespaced tool not in registry or disabled
   - `mcp_not_running` — MCP process not currently running
   - `mcp_crashed` — MCP was running but exited unexpectedly
   - `timeout` — child MCP did not respond within 30 seconds
   - Include error message and suggestive context (e.g., "Enable MCP 'foo' to use this tool")

#### ShipyardBridge Integration

9. **ShipyardBridge exposes gateway to Claude**
   - Listens on socket for Claude Desktop/Code connections
   - Implements socket protocol:
     - `gateway_discover` → list all tools with metadata
     - `gateway_call` → forward tool call to child MCP
     - `gateway_set_enabled` → toggle MCP or tool enabled state
   - No direct tool calls to MCPs; all go through gateway

10. **Request/response correlation** via request id
    - Each tool call has unique id (UUID or incremental)
    - Child MCP response includes matching id
    - MCPBridge correlates response to request, returns to sender
    - Handles out-of-order responses (child may respond in any order)

#### Gateway UI (GatewayView)

11. **Gateway tab** (⌘2 keyboard shortcut, second tab in main window)
    - Shows all aggregated tools grouped by MCP
    - For each MCP: name, enabled/disabled toggle, status (running/stopped)
    - For each tool: namespaced name, description, enabled/disabled toggle
    - MCP-level toggle disables all child tools visually
    - Tool-level toggle only active if MCP is enabled
    - Real-time update on MCP start/stop/restart

12. **Refresh button**
    - Manual refresh of tool discovery
    - Useful if tool list changes in child MCP without restart (edge case)
    - Calls `gateway_discover` and updates GatewayRegistry

### Nice to Have (Post-MVP)

1. **Tool search/filter** in GatewayView
   - Filter tools by keyword (name, description, MCP name)
   - Reduce visual clutter for large tool ecosystems

2. **Tool usage analytics**
   - Track which tools are called most frequently
   - Show in UI (e.g., badge on frequently used tools)

3. **Tool metadata browser**
   - Click on tool → show full schema, input_schema, description in detail pane
   - Useful for understanding what a tool does before enabling

4. **Bulk enable/disable**
   - "Enable all tools" / "Disable all tools" buttons
   - "Enable/disable all tools in MCP X" shortcuts

5. **Export/import gateway state**
   - Save toggle state to JSON (useful for onboarding, sharing config)
   - Import from JSON (restore state across machines)

6. **Tool groups/categories**
   - Allow user to create custom groups within an MCP (e.g., "Admin", "Read-Only")
   - Persist in UserDefaults, UI shows grouped toggles

---

## Design Decisions

### ADR 0003: Gateway Pattern — Single MCP Entry Point

**Decision:** Shipyard acts as a single aggregation point. Claude connects to Shipyard; Shipyard manages all child MCPs.

**Rationale:**
- **Scalability:** Adding new MCPs requires no changes to Claude; Shipyard discovers them automatically
- **Resilience:** If one MCP crashes, others remain accessible; Shipyard handles graceful degradation
- **UX:** Single connection, unified tool discovery, centralized enable/disable controls
- **Naming:** Prevents tool name collisions across MCPs (double underscore namespacing)
- **Persistence:** Single source of truth for enable/disable state (UserDefaults)

**Alternatives considered:**
- Direct Claude-to-MCP connections: scales poorly, no aggregation, scattered state
- Dumb proxy (no aggregation): still requires Claude to manage discovery; Shipyard just forwards

**Status:** Accepted, fully implemented.

### Namespacing Strategy: Double Underscore

**Decision:** Tools are namespaced as `{mcp-name}__{tool-name}` (double underscore).

**Rationale:**
- Matches Claude Code convention for delegated MCPs (transparent to Claude)
- Double underscore unlikely in tool names (single `_` is common)
- Demultiplexing is trivial: `split("__")` on first occurrence
- Prevents collisions: user can run two MCPs with same tool names without conflict

**Example:** MCP "anthropic-files" with tool "read_file" → namespaced as `anthropic-files__read_file`

**Status:** Implemented, matches existing convention.

### Dual-Level Enable/Disable Toggles

**Decision:** Two orthogonal toggle levels: MCP-level and tool-level.

**Rationale:**
- **MCP-level:** user can disable an entire server (e.g., during troubleshooting, resource constraints)
- **Tool-level:** user can selectively disable specific tools (e.g., "don't use the delete function")
- **Semantics:** clear mental model (disable server vs. disable capability within server)
- **Persistence:** separate UserDefaults keys, independent state management

**Precedence logic:**
```
tool_available = mcp_enabled AND tool_enabled
```

**Example:**
- MCP "llm-api" disabled → all tools unavailable (regardless of tool-level toggles)
- MCP "llm-api" enabled, tool "delete_account" disabled → other tools available, delete_account unavailable

**Status:** Implemented, state persisted in UserDefaults.

### Tool Call Timeout: 30 Seconds

**Decision:** All tool calls to child MCPs must complete within 30 seconds.

**Rationale:**
- **Responsiveness:** prevents hanging indefinitely if child MCP freezes
- **Developer experience:** sufficient for most operations (API calls, file I/O, GPU inference)
- **Error handling:** timeout returns `timeout` error with suggestion to increase or retry
- **Configurability:** could be made user-configurable post-MVP (not yet required)

**Status:** Implemented in MCPBridge tool call forwarding.

### Hot-Reload on MCP Lifecycle

**Decision:** Shipyard automatically re-discovers tools when MCPs start/stop/restart.

**Rationale:**
- **UX:** user sees tool list update in real-time without manual refresh
- **Correctness:** prevents stale tool list if MCP changes (e.g., plugin load/unload)
- **Robustness:** handles MCP crashes gracefully (tools become unavailable, not stuck in "available" state)

**Trigger mechanism:**
- MCPManager observes process lifecycle (didFinishLaunching, processDidTerminate, processDidCrash)
- On event, MCPManager calls GatewayRegistry.rediscover(mcp_name)
- GatewayRegistry calls MCPBridge.toolsList(mcp_name), updates internal registry
- GatewayView observes registry changes, updates UI

**Status:** Implemented, tested.

### Error Handling Semantics

**Decision:** Tool call errors are specific and suggestive (not generic "tool not found").

**Rationale:**
- **Debuggability:** user knows what went wrong (disabled? MCP crashed? timeout?)
- **UX:** error message suggests next action (enable MCP, restart MCP, increase timeout)
- **Robustness:** handles edge cases (MCP running but unresponsive, tool disabled, MCP crashed)

**Error categories:**
- `tool_unavailable` — tool exists but is disabled (MCP-level or tool-level)
- `mcp_not_running` — MCP process not running
- `mcp_crashed` — MCP was running but process exited
- `timeout` — MCP didn't respond within 30s

**Status:** Implemented in SocketServer dispatch logic.

### State Persistence: UserDefaults

**Decision:** Enable/disable state persists to UserDefaults (not SwiftData, not iCloud).

**Rationale:**
- **Simplicity:** UserDefaults is lightweight, minimal overhead
- **Scope:** state is per-machine (MCPs are local; no sync across devices)
- **Atomic writes:** synchronous writes prevent data loss on app termination
- **Backward compatibility:** defaults (all enabled) don't break existing setup

**Storage keys:**
- MCP-level: `shipyard.mcp.{mcp_name}.enabled` (Bool)
- Tool-level: `shipyard.tool.{mcp_name}.{tool_name}.enabled` (Bool)

**Migration:** if key doesn't exist, default to true (enabled).

**Status:** Implemented, fully tested.

---

## Data Flow: Tool Call Example

**Scenario:** Claude Code calls `anthropic-files__read_file`

```
1. Claude Code sends JSON-RPC request to Shipyard socket:
   {
     "jsonrpc": "2.0",
     "id": "req-12345",
     "method": "tools/call",
     "params": {
       "name": "gateway_call",
       "arguments": {
         "tool": "anthropic-files__read_file",
         "path": "/tmp/example.txt"
       }
     }
   }

2. ShipyardBridge receives on stdin, dispatches to SocketServer

3. SocketServer parses, routes "gateway_call" to GatewayRegistry

4. GatewayRegistry validates:
   - Tool "anthropic-files__read_file" exists? YES
   - MCP "anthropic-files" enabled? YES
   - Tool "read_file" enabled? YES
   - MCP process running? YES

5. GatewayRegistry calls MCPBridge.call(mcp_name: "anthropic-files", tool: "read_file", args: {...})

6. MCPBridge sends JSON-RPC to child's stdin:
   {
     "jsonrpc": "2.0",
     "id": "child-67890",
     "method": "tools/call",
     "params": {
       "name": "read_file",
       "arguments": { "path": "/tmp/example.txt" }
     }
   }

7. Child MCP reads stdin, executes tool, writes response to stdout:
   {
     "jsonrpc": "2.0",
     "id": "child-67890",
     "result": {
       "content": "file contents here"
     }
   }

8. MCPBridge reads stdout, correlates response by id, returns to SocketServer

9. SocketServer returns to ShipyardBridge:
   {
     "jsonrpc": "2.0",
     "id": "req-12345",
     "result": {
       "content": "file contents here"
     }
   }

10. ShipyardBridge writes to stdout (Claude Code reads)

11. Claude Code receives result, displays to user
```

**Error case:** if MCP disabled or tool disabled, step 4 returns `tool_unavailable` error at step 9.

**Timeout case:** if child doesn't respond in 30s, MCPBridge returns `timeout` error.

---

## Acceptance Criteria

### Discovery & Registry

- [ ] GatewayRegistry aggregates tools from all running MCPs without duplicates
- [ ] Tool names are namespaced as `{mcp-name}__{tool-name}` in registry
- [ ] `gateway_discover` returns all tools with correct metadata (name, description, input_schema, enabled)
- [ ] Discovery triggers automatically on MCP start, stop, and manual refresh
- [ ] GatewayRegistry is thread-safe (concurrent reads, no data corruption)

### Enable/Disable State

- [ ] MCP-level toggle persists to UserDefaults with key `shipyard.mcp.{mcp-name}.enabled`
- [ ] Tool-level toggle persists to UserDefaults with key `shipyard.tool.{mcp-name}.{tool-name}.enabled`
- [ ] Toggled state is restored on app restart
- [ ] Default state (all enabled) is applied if key doesn't exist
- [ ] MCP-level toggle disables all child tools (precedence logic correct)

### Tool Forwarding

- [ ] `gateway_call` routes to correct child MCP via MCPBridge
- [ ] Tool call returns child's response verbatim to caller
- [ ] Tool call timeout (30s) returns `timeout` error with suggestion
- [ ] Disabled MCP returns `mcp_not_running` or `tool_unavailable` error
- [ ] Disabled tool returns `tool_unavailable` error with suggestion to enable
- [ ] All errors include actionable error messages

### ShipyardBridge Integration

- [ ] ShipyardBridge socket accepts `gateway_discover`, `gateway_call`, `gateway_set_enabled` methods
- [ ] `gateway_discover` returns all aggregated tools
- [ ] `gateway_call` forwards tool call and returns response
- [ ] `gateway_set_enabled` updates toggle state and persists to UserDefaults
- [ ] Request/response correlation by id works correctly (out-of-order responses handled)

### UI (GatewayView)

- [ ] Gateway tab (⌘2) shows all MCPs grouped with tools
- [ ] MCP shows: name, status (running/stopped), enabled/disabled toggle
- [ ] Tool shows: namespaced name, description, enabled/disabled toggle
- [ ] MCP-level toggle disables all child tools visually (tool toggles disabled/grayed out)
- [ ] Tool-level toggle only active if MCP is enabled
- [ ] Toggling state in UI persists to UserDefaults and updates GatewayRegistry
- [ ] UI updates in real-time when MCP starts/stops/restarts
- [ ] Refresh button manually re-discovers tools

### Integration Tests

- [ ] End-to-end: Claude Code calls tool → Shipyard routes → child MCP executes → result returned
- [ ] Enable/disable state affects tool availability (correctly blocks unavailable tools)
- [ ] MCP crash is detected; tools become unavailable; error is returned to Claude
- [ ] Multiple concurrent tool calls are handled correctly (no race conditions)
- [ ] Tool call timeout is enforced; timeout error returned

---

## Implementation Plan

### Phase 1: Core Registry & Discovery (1-2 days)

1. **GatewayRegistry** struct
   - Data structure: `[String: [String: ToolMetadata]]` (mcp_name → tool_name → metadata)
   - Methods: `addTool()`, `removeTool()`, `toolForNamespacedName()`, `allTools()`
   - Thread-safe access (DispatchQueue or actor)

2. **Discovery logic** in MCPManager
   - For each running MCP, call MCPBridge.toolsList()
   - Aggregate into GatewayRegistry with namespaced names
   - Trigger on MCP start/stop

3. **Socket method** `gateway_discover`
   - Called by ShipyardBridge
   - Returns all tools in registry with metadata

### Phase 2: Enable/Disable State Management (1 day)

1. **UserDefaults wrapper** for toggle state
   - Read/write MCP-level: `shipyard.mcp.{mcp-name}.enabled`
   - Read/write tool-level: `shipyard.tool.{mcp-name}.{tool-name}.enabled`
   - Defaults: all true

2. **GatewayRegistry** updated
   - Include `enabled` field in ToolMetadata
   - Read toggle state from UserDefaults on init
   - Update on toggle change

### Phase 3: Tool Forwarding & Error Handling (1-2 days)

1. **SocketServer** dispatch logic
   - Parse `gateway_call` method
   - Validate: tool exists, MCP enabled, tool enabled, MCP running
   - Route to MCPBridge.call()
   - Handle errors (tool_unavailable, mpc_not_running, mcp_crashed, timeout)

2. **MCPBridge.call()** updated
   - Forward JSON-RPC to child stdin
   - Read response from stdout (with timeout 30s)
   - Correlate by request id
   - Return response or error

### Phase 4: ShipyardBridge Integration (1 day)

1. **ShipyardBridge** socket protocol
   - Expose `gateway_discover`, `gateway_call`, `gateway_set_enabled` methods
   - Route to GatewayRegistry/SocketServer
   - Return responses

2. **Socket method** `gateway_set_enabled`
   - Parse mcp_name and optional tool_name
   - Update toggle state (UserDefaults)
   - Update GatewayRegistry
   - Return success/error

### Phase 5: UI (GatewayView) (1-2 days)

1. **GatewayView** SwiftUI view
   - List of MCPs with toggle controls
   - List of tools per MCP with toggle controls
   - Status indicator (running/stopped)
   - Refresh button

2. **Observability**
   - GatewayRegistry publishes changes (Combine ObservableObject or async/await)
   - GatewayView observes and updates

### Phase 6: Integration Testing (1-2 days)

1. **Unit tests**
   - GatewayRegistry: add/remove/lookup tools
   - Toggle state: persist/restore, precedence logic
   - Namespacing: correct demultiplexing

2. **Integration tests**
   - End-to-end tool call: Claude → Shipyard → child MCP → response
   - Enable/disable state affects tool availability
   - MCP lifecycle (start/stop/crash) triggers re-discovery
   - Concurrent tool calls
   - Timeout enforcement

### Phase 7-8: Phase Shipped (Session 46+)

- **T2 integration tests added** (test with real Claude Code connection)
- **Fully implemented and shipped**

---

## Success Criteria

### Functional Success

1. **Single connection:** Claude Desktop/Code connects to Shipyard; all tools accessible via one connection
2. **Aggregation:** Shipyard discovers and lists all tools from all running MCPs (no manual configuration)
3. **Routing:** Tool calls are routed transparently to correct MCP without Claude intervention
4. **Visibility:** GatewayView shows all tools with MCP/tool-level toggles and real-time status
5. **Persistence:** Enable/disable state survives app restart
6. **Resilience:** MCP crash or timeout is handled gracefully; other MCPs unaffected

### Performance Success

1. **Discovery latency:** full discovery completes in <5s (even with 10+ MCPs)
2. **Tool call latency:** tool call forwarding adds <100ms overhead (RTT)
3. **Memory footprint:** registry uses <10MB for 100 tools

### Reliability Success

1. **No data loss:** toggle state is persisted atomically (no corruption on crash)
2. **No race conditions:** concurrent tool calls are handled correctly
3. **Error messages:** all errors are specific and actionable

### UX Success

1. **Discoverability:** new MCPs appear in tool list automatically (no manual registration)
2. **Control:** user can enable/disable any tool with one click
3. **Clarity:** UI clearly shows tool status (available/disabled/MCP not running)

---

## Unknowns & Risks

### Known Risks

1. **MCP lifecycle detection**
   - Risk: Shipyard may not detect MCP crash in real-time (ProcessDidTerminate notification delay)
   - Mitigation: Add periodic health check (ping MCP every 5s, detect crash)

2. **Tool list changes without restart**
   - Risk: Child MCP adds new tool, Shipyard doesn't see it until manual refresh or restart
   - Mitigation: Manual refresh button in UI; document limitation

3. **Concurrent tool calls to same MCP**
   - Risk: JSON-RPC correlation by id may fail if responses arrive out of order
   - Mitigation: MCPBridge uses explicit request/response matching (id correlation proven in tests)

4. **Timeout handling**
   - Risk: 30s timeout may be too short for some operations (slow API, GPU inference)
   - Mitigation: Make timeout configurable post-MVP; document in troubleshooting guide

5. **UserDefaults limits**
   - Risk: Tool list changes frequently, UserDefaults may grow large (1000+ tools)
   - Mitigation: Post-MVP, migrate to lightweight DB if needed; currently acceptable

### Open Questions

1. **Tool metadata updates**
   - Should Shipyard cache tool input_schema, or fetch fresh on each discovery?
   - Current: cache (faster discovery, may be stale if tool schema changes)
   - Decision: document that schema changes require re-discovery

2. **Tool groups/categories**
   - Should Shipyard support user-defined groups (e.g., "Admin", "Read-Only")?
   - Current: nice-to-have post-MVP
   - Decision: defer to Phase 2

3. **Tool usage tracking**
   - Should Shipyard track which tools are called (for analytics)?
   - Current: nice-to-have post-MVP
   - Decision: defer; can add without affecting core functionality

---

## Scope Boundaries

### In Scope
- Gateway registry and discovery
- Enable/disable toggles (MCP-level and tool-level)
- Tool forwarding and routing
- ShipyardBridge socket integration
- GatewayView UI
- Error handling (4 error categories)
- Timeout enforcement (30s)
- UserDefaults persistence
- Integration tests

### Out of Scope (Post-MVP)
- Tool search/filter
- Tool usage analytics
- Tool metadata browser
- Bulk enable/disable
- Export/import gateway state
- Tool groups/categories
- Configurable timeout
- Webhook-based MCP discovery (static local MCPs only)

---

## References

- **ADR 0003:** Gateway Pattern — Single MCP Entry Point
- **MCP Spec:** [spec.modelcontextprotocol.io](https://spec.modelcontextprotocol.io)
- **Claude Code MCP Delegation:** `{mcp-name}__{tool-name}` convention
- **Shipyard Architecture:** `_System/DevKB/architecture.md`

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-16 | AI assistant | Initial spec (post-implementation documentation) |
