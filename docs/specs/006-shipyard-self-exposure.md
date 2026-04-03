# Spec: Shipyard Self-Exposure

**Status:** Draft
**Author:** AI assistant
**Date:** 2026-03-26
**Version:** 1.0

---

## Problem Statement

Shipyard runs as a native macOS SwiftUI app, but it also operates as an MCP server itself, listening on a Unix domain socket at `~/.shipyard/data/shipyard.sock` and exposing tools like `shipyard_status`, `shipyard_health`, `shipyard_restart`, `shipyard_logs`, and `shipyard_gateway_discover`.

**The hidden feature:** This fact is completely invisible in the Gateway tab (⌘2) UI. Users cannot see:

1. **Shipyard's own server status** — whether the socket is listening, how many connections are active, uptime
2. **Management tools** — the full catalog of `shipyard_*` tools that Shipyard exposes to Claude
3. **Control surface** — start/stop/restart buttons, enable/disable toggles for individual tools
4. **Connection metadata** — socket path, transport info, connected clients

This creates an inconsistency: child MCPs are fully visible and controllable in the Gateway UI, but Shipyard (the orchestrator itself) is a black box. The user must rely on external tools or documentation to understand what Shipyard is doing, when it's available, or which of its tools are enabled.

**Impact:** Reduced transparency, potential confusion about tool availability, missed opportunities for user control and debugging.

---

## Vision Statement

**Expose Shipyard as a "first-class" managed MCP server in the Gateway tab, with full parity to child MCPs.** Treat Shipyard as a special server above the child MCP list with:

- **Status section** at the top of the Gateway detail pane
- **Identical control patterns** to children: status indicator, start/stop/restart buttons, uptime display
- **Full tool catalog** with enable/disable toggles per tool (same UI as children)
- **Connection metadata** (socket path, listener status, active client count)
- **Real-time updates** as tools are toggled or Shipyard's state changes

**Result:** Shipyard's internal workings are as visible and controllable as any child MCP. The gateway is no longer hiding itself.

---

## Requirements

### Must Have (MVP)

#### Shipyard Server Representation in Gateway Registry

1. **ShipyardServer abstraction** — treat Shipyard as a virtual MCPServer in the gateway context
   - Manifest-like metadata: name="shipyard", version (from app bundle), command="builtin"
   - State tracking: running (socket listening), stopped (socket not listening), error
   - Process-like stats: uptime (since app launch or socket creation), resource usage (optional, defer post-MVP)
   - Unique identifier to distinguish from child MCPs in the registry

2. **Shipyard server is always discoverable**
   - Always present in the gateway UI (cannot be removed or hidden)
   - State transitions tracked: socket listener status changes
   - Metadata refreshed on demand (socket path, current connections, enabled tools)

#### Tool Discovery for Shipyard

3. **Shipyard tool catalog discovery** (`shipyard_tools` socket method)
   - New socket method that returns list of all tools Shipyard exposes
   - Returns: `shipyard_status`, `shipyard_health`, `shipyard_logs`, `shipyard_restart`, `shipyard_gateway_discover`, `shipyard_gateway_call`, `shipyard_gateway_set_enabled`, `shipyard_restart`, plus any new tools added post-MVP
   - Metadata per tool: name (without `shipyard_` prefix in UI), description, input_schema
   - Triggered on demand (Gateway tab refresh, app startup)
   - Cached in GatewayRegistry like child MCP tools

4. **Namespace format for Shipyard tools**
   - Shipyard tools are exposed as `shipyard__{tool_name}` in the registry and gateway
   - Matches double-underscore convention (same as child MCPs)
   - Examples: `shipyard__status`, `shipyard__health`, `shipyard__logs`

#### Enable/Disable State for Shipyard Tools

5. **Tool-level enable/disable for Shipyard tools**
   - Each Shipyard tool has independent enable/disable toggle
   - State persisted to UserDefaults: `shipyard.tool.shipyard.{tool_name}.enabled`
   - Default: all tools enabled (backward compatible)
   - Precedence: tool disabled → tool unavailable to Claude

6. **No MCP-level toggle for Shipyard** (unique to Shipyard)
   - Shipyard cannot be disabled as a whole (it's always running and managing child MCPs)
   - Rationale: disabling Shipyard would break the entire gateway
   - Only tool-level toggles apply to Shipyard

#### Gateway UI for Shipyard Self-Exposure

7. **Special status header in Gateway detail pane**
   - Placed ABOVE the child MCP list (visual hierarchy: Shipyard first, then children)
   - Distinct visual treatment (e.g., different background color, border, or card styling)
   - Shows: "Shipyard" as the title, status indicator (running/not-running), uptime
   - Control buttons: Restart (restart socket listener?), Logs (access Shipyard app logs)
   - No Start/Stop buttons (Shipyard runs for the entire app lifetime)

8. **Shipyard tool list in detail pane**
   - After Shipyard status header, show its tool catalog (just like child MCPs)
   - Tools grouped under "Shipyard" section
   - For each tool: name (displayed as `status`, `health`, `logs`, etc., without `shipyard_` prefix), description, enable/disable toggle
   - Disabled tools shown with grayed-out toggle (same as child MCP disabled tools)

9. **Real-time updates**
   - Shipyard status refreshes when socket listener starts/stops
   - Tool catalog updates when new tools are added (unlikely, but prepared)
   - Enable/disable state reflects immediately in UI and in GatewayRegistry

#### Socket Protocol Extension

10. **New socket method: `shipyard_tools`**
    - Called by GatewayRegistry during tool discovery phase
    - Returns JSON array of tools exposed by Shipyard
    - Format matches child MCP tools (name, description, input_schema)
    - Called on app startup and on manual refresh

11. **Tool-level enable state queries**
    - Modify `shipyard_status` response to include enabled state per tool (optional, defer if scope creep)
    - Or, keep enable/disable state purely in the UI/GatewayRegistry (simpler, sufficient)

#### Data Flow & State Management

12. **GatewayRegistry tracks Shipyard as special case**
    - Internal logic: `isShipyardServer(server)` to identify Shipyard vs. child MCPs
    - Shipyard tools stored alongside child MCP tools in registry
    - Precedence: Shipyard tools always show first in detail view

13. **SocketServer introspection**
    - SocketServer exposes its own listening state and connection count
    - Metadata available via status query or dedicated method
    - Uptime calculated from app launch time (Process.runtime or stored timestamp)

### Nice to Have (Post-MVP)

1. **Shipyard restart button behavior** — clarify what "restart" does for Shipyard
   - Option A: Restart the socket listener (stop and re-bind socket)
   - Option B: Full app restart (app quit and relaunch — not practical)
   - Recommend: defer to post-MVP clarification with user

2. **Resource usage for Shipyard** — show CPU and memory usage like child MCPs
   - Could extract from `Process.processInfo` for current app
   - Lower priority (diagnostic, not essential for MVP)

3. **Shipyard status indicators** — detailed state info
   - Socket listener active/inactive
   - Number of connected clients
   - Child MCP count and aggregate status
   - Deferred to post-MVP

4. **Bulk enable/disable for Shipyard tools**
   - "Enable all Shipyard tools" / "Disable all Shipyard tools" shortcuts
   - Similar to child MCP bulk controls (post-MVP feature)

5. **Tool input schema browser**
   - Click on Shipyard tool → show full schema (input_schema, description)
   - Same as child MCP tool details view (post-MVP)

---

## Design Decisions

### ADR 0006: Shipyard Self-Exposure — Treating the Orchestrator as a Visible Managed Server

**Decision:** Shipyard is exposed in the Gateway tab as a special MCP server with full control and visibility parity to child MCPs.

**Rationale:**
- **Consistency:** Users see all MCP-like services (Shipyard + children) in one place
- **Transparency:** Shipyard's tools and state are visible; no hidden "magic"
- **Control:** Users can enable/disable individual Shipyard tools (e.g., disable `logs` if desired)
- **Discoverability:** New users learn that Shipyard has its own tool ecosystem
- **UX:** No special UI patterns for Shipyard — reuse existing Gateway patterns for familiarity

**Alternatives considered:**
- Hidden Shipyard (current state): keeps Shipyard invisible, but unclear and inconsistent
- Separate "System" tab: adds UI complexity, requires new navigation pattern
- Shipyard in "About" or "Settings" tab: unclear, not discoverable

**Status:** Accepted, ready for implementation.

### Design: Shipyard Placement — Above Child MCPs in Detail View

**Decision:** Shipyard status and tools appear at the top of the Gateway detail pane, ABOVE the child MCP list.

**Rationale:**
- **Hierarchy:** Orchestrator is conceptually "above" children (owns them, manages them)
- **Discoverability:** first thing user sees when opening Gateway
- **UX clarity:** visual separation between Shipyard and child MCPs (distinct card or section)
- **Consistency:** matches app architecture (Shipyard is parent, children are managed)

**Example layout:**
```
┌─────────────────────────────────────────────────────┐
│ Shipyard (Special Status Card)                      │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│ Status: Running | Uptime: 4h 23m | [Restart] [Logs]│
│                                                     │
│ Tools:                                              │
│   ☑ status      | Returns server status             │
│   ☑ health      | Runs health checks                │
│   ☑ logs        | Returns system logs               │
│   ☑ gateway_... | Gateway routing tools             │
│                                                     │
├─────────────────────────────────────────────────────┤
│ Child MCPs (Normal List)                            │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│ [Server 1]   (running) [  ] [⟳] [⊗]               │
│   - tool-a   [✓]                                    │
│   - tool-b   [✓]                                    │
│ [Server 2]   (stopped) [disable] [▶]              │
│   - tool-x   [✗]                                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Status:** Accepted.

### Design: No Shipyard MCP-Level Toggle

**Decision:** Shipyard cannot be disabled as an MCP server (unlike child MCPs).

**Rationale:**
- **Architecture:** Disabling Shipyard would break the entire gateway pattern (no tool routing)
- **Consistency:** the socket must always listen for Claude connections
- **Safety:** prevents accidental disabling that would make all tools unavailable

**Implementation:** UI shows Shipyard status as "running" (always), no toggle button for MCP-level enable/disable. Only tool-level toggles apply.

**Status:** Accepted.

### Design: Shipyard Tools Use Double-Underscore Namespace

**Decision:** Shipyard tools follow the same namespacing convention as child MCPs: `shipyard__{tool_name}`.

**Rationale:**
- **Consistency:** same naming pattern everywhere in the gateway
- **Clarity:** Claude sees `shipyard__status`, `shipyard__health`, etc., clearly marking them as Shipyard-managed
- **Demultiplexing:** SocketServer.dispatchRequest can use the same parsing logic for all namespaced tools

**Example:** `shipyard__status`, `shipyard__gateway_discover`, `shipyard__logs`

**Note:** In the UI, displayed without the `shipyard__` prefix (just show "status", "health", etc.) to avoid visual clutter.

**Status:** Accepted.

### Design: Shipyard Tools Always Enabled by Default

**Decision:** All Shipyard tools default to enabled. Users can selectively disable tools but cannot disable Shipyard as a whole.

**Rationale:**
- **UX:** sensible defaults (all tools available)
- **Backward compatible:** existing Claude connections see all Shipyard tools immediately
- **Safety:** critical tools (e.g., `gateway_discover`) are available by default
- **Flexibility:** users can disable tools if desired (e.g., disable `logs` for privacy)

**Storage:** `shipyard.tool.shipyard.{tool_name}.enabled` in UserDefaults (defaults to true if key doesn't exist).

**Status:** Accepted.

---

## Acceptance Criteria

### Discovery & Registry

- [ ] GatewayRegistry recognizes Shipyard as a special server (distinct from child MCPs)
- [ ] `shipyard_tools` socket method returns all Shipyard tools with metadata
- [ ] Shipyard tools are cached in GatewayRegistry like child MCP tools
- [ ] Tools are namespaced as `shipyard__{tool_name}` in the registry
- [ ] Tool discovery triggers on app startup and manual refresh (no per-tool refresh)

### Enable/Disable State

- [ ] Shipyard tool enable/disable state persists to UserDefaults
- [ ] Key format: `shipyard.tool.shipyard.{tool_name}.enabled`
- [ ] Default state (all enabled) is applied if key doesn't exist
- [ ] UI reflects enabled/disabled state correctly (toggles, grayed out)
- [ ] Disabled Shipyard tools return `tool_unavailable` error when called

### Gateway UI

- [ ] Gateway detail pane shows Shipyard status card at the top (above child MCPs)
- [ ] Shipyard card shows: title, status (running), uptime, [Restart] and [Logs] buttons
- [ ] Shipyard card is visually distinct from child MCP cards (color, border, or styling)
- [ ] Shipyard tool list appears in detail pane (just like child MCPs)
- [ ] Tools displayed without `shipyard__` prefix (e.g., "status", "health", "logs")
- [ ] Each tool shows toggle for enable/disable
- [ ] Disabled tools are grayed out, toggle is disabled
- [ ] UI updates in real-time when tool enable/disable state changes

### Socket Protocol

- [ ] New socket method `shipyard_tools` returns array of Shipyard tools
- [ ] Response format matches child MCP tools: name, description, input_schema
- [ ] Method called during gateway discovery phase
- [ ] Method succeeds with empty array if no tools (edge case, test)

### State Management & Real-Time Updates

- [ ] Toggling a Shipyard tool enable/disable state in UI updates GatewayRegistry immediately
- [ ] Disabled Shipyard tool cannot be called via `gateway_call` (returns error)
- [ ] SocketServer.dispatchRequest handles `shipyard__{tool_name}` naming correctly
- [ ] Shipyard status (running/uptime) updates without manual refresh

### Integration

- [ ] GatewayView renders Shipyard status card and tool list without errors
- [ ] Refreshing tool discovery includes Shipyard tools (no separate refresh)
- [ ] Toggling child MCP tools doesn't affect Shipyard tools and vice versa

---

## Implementation Plan

### Phase 1: Socket Server Introspection & Tool Discovery (1 day)

1. **Add `shipyard_tools` socket method**
   - Implement in SocketServer.dispatchRequest
   - Return hardcoded list of Shipyard tools (status, health, logs, gateway_discover, gateway_call, gateway_set_enabled, restart, shipyard_tools)
   - Include descriptions and empty input_schema for now

2. **Extend GatewayRegistry to recognize Shipyard**
   - Add logic to identify Shipyard as special server in toolCatalog()
   - Create synthetic MCPServer-like representation for Shipyard
   - Store Shipyard tools under namespace `shipyard__{tool_name}`

3. **Test: Verify `shipyard_tools` returns correct data via socket**

### Phase 2: Enable/Disable State for Shipyard Tools (1 day)

1. **Add UserDefaults storage for Shipyard tool toggles**
   - Key: `shipyard.tool.shipyard.{tool_name}.enabled`
   - Read state on app startup, cache in GatewayRegistry

2. **Implement toggle logic in SocketServer**
   - `gateway_set_enabled` already exists; extend to handle `shipyard__{tool_name}`
   - Update UserDefaults on toggle
   - Publish state change to GatewayRegistry

3. **Modify `gateway_call` validation**
   - Check if Shipyard tool is enabled before routing
   - Return `tool_unavailable` error if disabled

4. **Test: Verify toggle state persists and affects tool availability**

### Phase 3: Gateway UI for Shipyard (1-2 days)

1. **Create ShipyardStatusCard component**
   - VStack: title "Shipyard", status indicator (running), uptime
   - HStack: [Restart] [Logs] buttons
   - Distinct visual styling (e.g., background color, corner radius, shadow)

2. **Extend GatewayView to show Shipyard first**
   - Replace hardcoded server list with logic: Shipyard first, then child MCPs
   - In detail view: show ShipyardStatusCard, then tool list for Shipyard

3. **Shipyard tool list view**
   - Reuse existing tool row component (same as child MCPs)
   - Display tools without `shipyard__` prefix
   - Toggle enable/disable per tool

4. **Real-time updates**
   - GatewayRegistry publishes Shipyard state changes (Combine or async/await)
   - GatewayView observes and refreshes UI

5. **Test: Verify UI renders without errors, toggles work**

### Phase 4: Integration & Testing (1 day)

1. **Unit tests**
   - GatewayRegistry: Shipyard server detection and tool storage
   - UserDefaults: toggle state persistence
   - SocketServer: `shipyard_tools` method, toggle handling

2. **Integration tests**
   - End-to-end: refresh discovery → Shipyard tools appear → toggle tool → state persists → tool unavailable in gateway_call
   - Shipyard + child MCPs: both appear in UI, independent toggles

3. **Smoke test: Manual QA in running app**
   - Open Gateway tab
   - Verify Shipyard appears at top
   - Verify tools list shows
   - Toggle a tool and verify disabled state

---

## Data Flow: Shipyard Self-Exposure

**Scenario:** User opens Gateway tab; Shipyard tools are discovered and displayed.

```
1. User opens Gateway tab (⌘2)

2. GatewayView.task triggers auto-discovery
   - Calls gatewayRegistry.discoverTools() or similar

3. GatewayRegistry.discoverTools():
   - For each running child MCP: call MCPBridge.discoverTools()
   - For Shipyard: call SocketServer.handleShipyardTools()
   - Aggregate all tools (children + Shipyard)
   - Publish updates to observers

4. SocketServer.handleShipyardTools():
   - Return hardcoded list of tools exposed by Shipyard
   - Include metadata: name, description, input_schema (empty or minimal)
   - Return JSON array

5. GatewayRegistry stores Shipyard tools:
   - Key: `shipyard__{tool_name}` (e.g., `shipyard__status`, `shipyard__health`)
   - Metadata: name, description, input_schema, enabled (read from UserDefaults)
   - Mark as "Shipyard" source (distinguish from child MCPs)

6. GatewayView renders:
   - Sidebar: list of servers (children + Shipyard at top)
   - Detail pane:
     - ShipyardStatusCard (status, uptime, buttons)
     - Tool list for Shipyard (filtered: mcp_name == "shipyard")
     - Tool list for selected child MCP (if any)

7. User toggles a Shipyard tool:
   - GatewayView calls gatewayRegistry.setToolEnabled(tool: "shipyard__status", enabled: false)
   - GatewayRegistry updates UserDefaults: `shipyard.tool.shipyard.status.enabled = false`
   - Publishes state change
   - UI updates immediately (toggle shows disabled)

8. Claude calls shipyard__status:
   - ShipyardBridge receives request
   - SocketServer validates: tool enabled? NO
   - Returns `tool_unavailable` error
   - Tool is unavailable until user re-enables it
```

---

## Success Criteria

### Functional Success

1. **Shipyard is visible** — Shipyard appears in Gateway tab as a special server at the top
2. **Tools are discoverable** — all Shipyard tools appear in the tool list with correct metadata
3. **Control is available** — user can enable/disable each Shipyard tool with UI toggle
4. **State persists** — toggle state survives app restart (stored in UserDefaults)
5. **Tool availability is enforced** — disabled Shipyard tools return `tool_unavailable` error when called
6. **Real-time updates** — UI reflects state changes immediately without manual refresh

### UX Success

1. **No confusion** — it's clear that Shipyard is a managed server like any other
2. **Consistency** — Shipyard uses identical UI patterns to child MCPs (same rows, toggles, detail panes)
3. **Hierarchy** — Shipyard's position at the top visually represents its role as orchestrator
4. **Discoverability** — new users naturally see Shipyard's tools and understand what they do

### Performance Success

1. **Discovery latency** — Shipyard tool discovery completes in <1s (minimal overhead vs. child MCP discovery)
2. **UI responsiveness** — toggling Shipyard tool enables immediately (no network latency)
3. **Memory footprint** — Shipyard tools add <1KB to GatewayRegistry (small metadata)

### Reliability Success

1. **No regressions** — existing child MCP functionality unaffected
2. **Backward compatibility** — apps without `shipyard_tools` method still work (graceful degradation)
3. **No data loss** — UserDefaults writes are atomic (no corruption on crash)

---

## Unknowns & Risks

### Known Risks

1. **Circular dependency — Shipyard managing itself**
   - Risk: Shipyard disables the `gateway_discover` or `gateway_call` tools, breaking the gateway
   - Mitigation: Prevent disabling of critical tools (gateway_discover, gateway_call) via UI validation; document policy
   - Alternative: Allow all tools to be disabled (user responsibility), but document the consequences

2. **Shipyard uptime calculation**
   - Risk: Uptime should reflect socket listener lifetime, but we may only have app launch time
   - Mitigation: Store socket creation timestamp in SocketServer, use for uptime calculation
   - Deferrable: show app uptime as approximation post-MVP

3. **Tool list staleness**
   - Risk: if Shipyard adds new tools (via code update), they won't appear until app restart
   - Mitigation: manual "Refresh" button in Gateway allows re-discovery
   - Impact: low (unlikely to add tools dynamically post-MVP)

4. **Namespace conflicts**
   - Risk: a child MCP named "shipyard" could create naming conflicts (e.g., `shipyard__status` ambiguity)
   - Mitigation: Shipyard's identity is hardcoded; impossible for child to be named "shipyard" (reserved)
   - Deferrable: validate manifest parsing to reject reserved names

### Open Questions

1. **What does "Restart" button do for Shipyard?**
   - Option A: Restart socket listener (stop and re-bind socket)
   - Option B: Not applicable (defer post-MVP)
   - Recommend: defer; clarify with user before implementation

2. **Should Shipyard show resource usage (CPU, memory)?**
   - Could extract from `Process.processInfo` for current app
   - Post-MVP (diagnostic, lower priority)

3. **Should some Shipyard tools be "protected" from disabling?**
   - Example: disable `gateway_call` → gateway breaks
   - Option: UI prevents disabling critical tools
   - Option: allow disabling anything, user responsibility
   - Recommend: defer; default to "allow all" post-MVP

4. **How many concurrent socket connections should Shipyard track?**
   - Nice to have metadata (connection count, client IPs)
   - Post-MVP (diagnostic)

---

## Scope Boundaries

### In Scope (MVP)

- Shipyard appears in Gateway as special server above child MCPs
- Shipyard status card shows: title, running status, uptime (app launch time), [Restart] [Logs] buttons
- Shipyard tool list with enable/disable toggles per tool
- `shipyard_tools` socket method to discover Shipyard tools
- UserDefaults persistence for tool enable/disable state
- Real-time UI updates when toggle state changes
- Tool unavailability enforcement (disabled tools return errors)
- Visual distinction for Shipyard card (styling, placement)
- Namespacing: `shipyard__{tool_name}` for all Shipyard tools
- No MCP-level toggle for Shipyard (always running)

### Out of Scope (Post-MVP)

- Restart button behavior clarification (defer until needed)
- Resource usage display (CPU, memory)
- Detailed connection tracking (active client count, IPs)
- Protection of critical tools from disabling
- Bulk enable/disable for Shipyard tools
- Tool input schema browser
- Export/import Shipyard tool state
- Dynamic tool discovery without app restart (tool list is static post-MVP)
- Separate "Shipyard" tab or modal (use existing Gateway UI)

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      GatewayView (UI)                         │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ ShipyardStatusCard                                       │ │
│  │  Status: Running | Uptime: 4h 23m | [Restart] [Logs]    │ │
│  │  Tools: status (enabled), health (enabled), ...          │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Child MCP Cards (normal list)                           │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
              ▲
              │ observes
              │
┌──────────────────────────────────────────────────────────────┐
│              GatewayRegistry (state manager)                  │
│                                                               │
│  - Tracks Shipyard as special server                          │
│  - Stores Shipyard tools (shipyard__status, etc.)            │
│  - Reads/writes enable/disable state from UserDefaults       │
│  - Publishes state changes to UI                             │
│  - Namespaces: child MCP tools + Shipyard tools             │
└──────────────────────────────────────────────────────────────┘
              ▲
              │ calls / publishes to
              │
┌──────────────────────────────────────────────────────────────┐
│              SocketServer (Shipyard core)                     │
│                                                               │
│  - Listens on ~/.shipyard/data/shipyard.sock                 │
│  - Methods: status, health, logs, gateway_discover,          │
│    gateway_call, gateway_set_enabled, restart,               │
│    shipyard_tools (NEW)                                      │
│                                                               │
│  - Exposes Shipyard state: listening?, uptime, tool list     │
│  - Enforces tool enable/disable via gateway_call validation  │
└──────────────────────────────────────────────────────────────┘
              ▲
              │ calls
              │
┌──────────────────────────────────────────────────────────────┐
│              UserDefaults (persistence)                       │
│                                                               │
│  - shipyard.tool.shipyard.status.enabled (bool, default true)│
│  - shipyard.tool.shipyard.health.enabled (bool, default true)│
│  - ... (one per Shipyard tool)                               │
└──────────────────────────────────────────────────────────────┘
```

---

## Testing Strategy

### Unit Tests

1. **GatewayRegistry tests**
   - Shipyard server detection (isShipyardServer)
   - Tool namespace handling (shipyard__toolname)
   - UserDefaults read/write for Shipyard tools

2. **SocketServer tests**
   - `shipyard_tools` method returns correct tools
   - `gateway_call` rejects disabled Shipyard tools
   - `gateway_set_enabled` updates UserDefaults for Shipyard tools

3. **UserDefaults tests**
   - Tool enable/disable state persists across writes
   - Default state (all enabled) applied if key missing
   - State survives app restart (simulated via UserDefaults read after write)

### Integration Tests

1. **End-to-end discovery flow**
   - App startup → gateway_discover triggered → Shipyard tools appear in GatewayRegistry
   - Verify Shipyard tools coexist with child MCP tools (no collisions)

2. **Enable/disable state flow**
   - Toggle tool in UI → GatewayRegistry updated → UserDefaults written
   - Disable Shipyard tool → call via gateway_call → returns tool_unavailable error
   - Re-enable tool → call succeeds

3. **UI rendering**
   - GatewayView renders Shipyard status card (no errors, correct layout)
   - Shipyard tool list renders with correct toggles
   - Toggle interaction triggers state update

4. **Real-time updates**
   - Toggle Shipyard tool → UI updates immediately (no manual refresh needed)
   - Enable/disable state reflects in detail pane

### Smoke Test (Manual QA)

1. Open Shipyard app
2. Navigate to Gateway tab (⌘2)
3. Verify Shipyard appears at top of detail pane
4. Verify Shipyard status shows "Running" and uptime
5. Verify Shipyard tools list shows below status (status, health, logs, etc.)
6. Toggle a Shipyard tool (e.g., disable "logs")
7. Verify toggle state persists (is it still disabled after restart?)
8. Verify disabled tool returns error when called via claude (optional, requires Claude connection)
9. Verify child MCPs still appear and function normally

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-26 | AI assistant | Initial spec — Shipyard self-exposure in Gateway tab |

---

## References

- **Spec 002-gateway.md** — Gateway feature specification (patterns, architecture, naming conventions)
- **Spec 001-server-management.md** — Server management and lifecycle control
- **Architecture Diagram:** SocketServer, GatewayRegistry, GatewayView integration
- **MCP Socket Protocol:** tool discovery, tool call routing, enable/disable state management
- **UserDefaults Storage:** toggle state persistence pattern (matches child MCP tools)
