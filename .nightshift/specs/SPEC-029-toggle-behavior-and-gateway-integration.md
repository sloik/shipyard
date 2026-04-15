---
id: SPEC-029
template_version: 2
priority: 2
layer: 2
type: feature
status: done
after: [SPEC-028]
prior_attempts:
  - date: 2026-04-15
    outcome: "Agent claimed all implemented and tests pass, but toggles do not work in the running app. Code analysis shows the gateway policy store may not be wired into the web server correctly at startup, or the toggle API calls fail silently. Implementation appears complete on paper but feature is non-functional."
created: 2026-04-15
completed: 2026-04-15
root_cause: |
  Three bugs found by second-attempt agent:

  1. notifications/tools/list_changed was never sent (R8, R11 not implemented). The previous
     agent wrote toggle handlers and gateway filtering correctly, but the shipyard-mcp bridge
     had no mechanism to notify Claude when policy changed. Claude would cache the tool list
     indefinitely. Fixed by adding watchPolicyAndNotify() goroutine in shipyard-mcp that polls
     /api/gateway/policy every 2 seconds, detects changes via SHA-256 hash, and writes
     {"jsonrpc":"2.0","method":"notifications/tools/list_changed"} to stdout.

  2. handleMCPPassthrough had no initialize handler (R7). The switch fell through to the proxy
     forwarding code for "initialize", returning a child server's capabilities instead of
     Shipyard's gateway capabilities. This meant listChanged: true was never declared in the
     auth-disabled (passthrough) path. Fixed by adding an "initialize" case that returns the
     gateway-level response directly.

  3. tools/call in handleMCPPassthrough fell through to broken routing after the gateway check.
     After verifying a server__tool was not disabled, the code fell through to extractPassthroughServer()
     which looks for a "server" field in params — absent in tools/call params — then forwarded the
     full "server__tool" name to an arbitrary child server, which would reject it as unknown. Fixed
     by routing directly to the correct child server with the bare tool name (prefix stripped).
---

# Toggle Behavior, Gateway Integration & MCP Compliance

## Problem

SPEC-028 delivered the visual toggle components and the persistence/API layer. However several behavioral aspects are incomplete or incorrect:

1. **Toggle sync is fragile**: The sidebar and detail panel toggles update each other via full re-renders or manual DOM patching. WebSocket `toggle_changed` broadcasts exist but the UI handler for multi-tab sync may not re-render correctly when the toggle source is another tab.

2. **Disabled tool detail panel lacks distinct visual state**: When a tool is disabled, the Execute button is disabled and a hint appears, but the rest of the detail panel (schema form, description, title row) looks identical to the enabled state. The design system has a `ToolList/ItemDisabled` component with `opacity: 0.5` — a comparable visual treatment should apply to the detail panel content area.

3. **Gateway does not send `notifications/tools/list_changed`**: Per the MCP specification (2025-11-25), when the available tool list changes, a server declaring `listChanged` capability SHOULD send a `notifications/tools/list_changed` JSON-RPC notification. Toggling a tool on/off changes what `tools/list` returns, but Shipyard does not emit this notification to connected clients. This means Claude (or any MCP client) won't know the tool list changed until it re-fetches.

4. **Gateway returns HTTP 403 for disabled tools**: The current implementation returns HTTP 403 with a plain message when a disabled tool is called. The MCP spec defines two error mechanisms: Protocol Errors (JSON-RPC error with code `-32602` for unknown tools) and Tool Execution Errors (result with `isError: true`). A disabled tool should use Protocol Error `-32602` since the tool is effectively not in the list, matching the "Unknown tool" pattern.

5. **Shipyard built-in tools cannot be disabled**: The `is_self` flag hard-blocks all Shipyard tools (status, list_servers, restart, stop) from being toggled. Users should be able to disable individual Shipyard tools — for example, disabling `stop` or `restart` to prevent Claude from accidentally stopping servers. The Shipyard gateway process itself must remain running (it's the orchestrator), but individual tools it exposes should be toggleable.

## Requirements

### Toggle Sync

- [x] R1: Sidebar toggle and detail panel toggle for the same tool MUST always be in sync. Toggling one immediately updates the other without a full sidebar re-render.
- [x] R2: WebSocket `toggle_changed` events from the server MUST update both the sidebar toggle and the detail panel toggle (if the affected tool is currently selected). This ensures multi-tab sync.
- [x] R3: Optimistic UI: toggle flips immediately on click; if the API call fails, revert to previous state and show a toast error.

### Disabled Tool Detail Panel

- [x] R4: When a disabled tool is selected in the sidebar, the detail panel MUST show a visual "disabled" state:
  - Title row: Switch/Off toggle, tool name at reduced opacity or `$text-muted` color
  - Schema form: visible but all input fields disabled (not editable)
  - Execute button: disabled, label changed to "Tool Disabled" (not just hint text)
  - A banner or inline message: "This tool is disabled. Enable it to execute."
- [x] R5: When a tool is disabled while it's currently selected in the detail panel, the panel transitions to the disabled visual state without deselecting the tool.
- [x] R6: When a server is disabled, all its tools in the detail panel show the disabled state with message: "Server is disabled. Enable the server first."

### MCP Gateway Compliance

- [x] R7: Shipyard gateway MUST declare `capabilities.tools.listChanged: true` in its MCP `initialize` response.
- [x] R8: When a tool's effective enabled state changes (either via tool toggle or server toggle), the gateway MUST send `notifications/tools/list_changed` JSON-RPC notification to all connected MCP clients (e.g., Claude).
- [x] R9: `tools/list` response MUST exclude disabled tools entirely (not include them with `enabled: false`). A disabled tool is invisible to MCP clients — as if it doesn't exist.
- [x] R10: `tools/call` for a disabled tool MUST return a JSON-RPC Protocol Error with code `-32602` and message `"Unknown tool: {name}"`. This is consistent with the MCP spec's error handling for unknown tools — from the client's perspective, a disabled tool does not exist.
- [x] R11: Re-enabling a tool MUST trigger `notifications/tools/list_changed` so clients re-fetch and discover the newly available tool.

### Shipyard Built-in Tool Toggles

- [x] R12: Remove the `is_self` hard-block on tool toggles. Shipyard's own tools (status, list_servers, restart, stop) MUST be individually toggleable, same as any other server's tools.
- [x] R13: The Shipyard server-level toggle remains hidden/always-on (the gateway process cannot disable itself). Only individual tool-level toggles are exposed.
- [x] R14: Default state for Shipyard tools: all enabled (backward compatible).
- [x] R15: When a Shipyard tool is disabled via toggle, it is excluded from `tools/list` and returns `-32602` on `tools/call`, same as any other disabled tool (R9, R10).

## Acceptance Criteria

### Toggle Sync

- [x] AC 1: Click sidebar toggle Off → detail panel toggle (if same tool selected) flips to Off within the same render frame — no flicker, no delay
- [x] AC 2: Click detail panel toggle Off → sidebar toggle for that tool flips to Off immediately
- [x] AC 3: Open two browser tabs on Tools page → disable tool in Tab A → Tab B's sidebar and detail panel reflect the change within 1 second (via WebSocket)
- [x] AC 4: API failure on toggle → toggle reverts to previous state, toast displays "Failed to update toggle"

### Disabled Tool Detail Panel

- [x] AC 5: Select an enabled tool → disable it → detail panel transitions: Execute button shows "Tool Disabled" (disabled), schema form inputs become read-only/disabled, banner appears
- [x] AC 6: Disable a server → select any of its tools → detail panel shows "Server is disabled" message, Execute button disabled
- [x] AC 7: Re-enable the tool/server → detail panel returns to normal enabled state, Execute button re-enabled

### MCP Gateway Compliance

- [x] AC 8: `initialize` response includes `"tools": { "listChanged": true }` in capabilities
- [x] AC 9: Disable tool "read_file" → connected MCP client receives `notifications/tools/list_changed` notification
- [x] AC 10: After notification, client calls `tools/list` → "read_file" is NOT in the response
- [x] AC 11: Client calls `tools/call` with `name: "read_file"` → receives JSON-RPC error `{ "code": -32602, "message": "Unknown tool: read_file" }`
- [x] AC 12: Re-enable "read_file" → `notifications/tools/list_changed` sent → next `tools/list` includes "read_file" again
- [x] AC 13: Disable entire server → one `notifications/tools/list_changed` sent (not one per tool) → all server's tools disappear from `tools/list`

### Shipyard Built-in Tools

- [x] AC 14: Shipyard tool rows in the sidebar have functional toggle switches (not disabled, no "cannot be disabled" tooltip)
- [x] AC 15: Disabling Shipyard's `restart` tool → `tools/list` no longer includes `restart` → calling `restart` returns `-32602`
- [x] AC 16: Shipyard server card on Servers tab has no server-level toggle (or always-on, non-interactive)
- [x] AC 17: All Shipyard tools default to enabled on fresh install and after upgrade (backward compatible)

## Context

### Existing Implementation (from SPEC-028)

- **Toggle state persistence**: `gateway/policy.go` — `persistedPolicy` struct with `Servers` and `Tools` maps, JSON file at `~/.config/shipyard/toggle-state.json`, atomic write
- **API routes**: `PUT /api/servers/{name}/enabled`, `PUT /api/tools/{server}/{tool}/enabled` in `server.go`
- **Gateway filtering**: `gateway_discover` augments tool list with `enabled` and `server_enabled` fields; `gateway_call` returns HTTP 403 for disabled tools
- **WebSocket broadcast**: `toggle_changed` events with target, name, server, tool, enabled fields
- **UI toggle sync**: `toggleTool()` and `toggleDetailPanelTool()` in `index.html` with optimistic updates and `updateExecuteButtonState()`

### MCP Specification Reference (2025-11-25)

- **`tools/list`**: Returns array of `Tool` objects. Only available tools should be listed.
- **`tools/call`**: Invokes a tool. Unknown tool → JSON-RPC Protocol Error code `-32602`, message "Unknown tool: {name}"
- **`notifications/tools/list_changed`**: Server → client notification. Servers declaring `listChanged: true` SHOULD send when tool list changes. Client then re-fetches via `tools/list`.
- **Error types**: Protocol Errors (JSON-RPC error, code `-32602` for unknown/invalid) vs Tool Execution Errors (`isError: true` in result for runtime failures)
- **Capability declaration**: `{ "capabilities": { "tools": { "listChanged": true } } }`

### Design Reference (UX-002)

- `ToolList/ItemDisabled` (`dDOm8`): opacity 0.5, Switch/Off ref, same layout as ItemDefault
- No dedicated "disabled detail panel" screen exists in UX-002 — R4 requirements are derived from the sidebar disabled pattern extended to the detail panel

## Scenarios

1. **Disable a single tool**: User toggles `write_file` Off in sidebar → sidebar row grays out (opacity 0.5) → detail panel (if showing `write_file`) transitions to disabled state → Claude receives `notifications/tools/list_changed` → Claude's next `tools/list` omits `write_file` → Claude tries to call `write_file` → gets `-32602 Unknown tool` → user re-enables → notification sent → Claude sees `write_file` again.

2. **Multi-tab sync**: User has two browser tabs open. Tab A disables `read_file`. Server broadcasts `toggle_changed` via WebSocket. Tab B receives it, updates sidebar toggle to Off, updates detail panel if `read_file` is selected.

3. **Disable Shipyard built-in tool**: User toggles `restart` Off → toggle works like any other tool → `restart` removed from Claude's tool list → Claude cannot restart servers → user re-enables when needed.

4. **Disable entire server**: User toggles lmstudio server Off → all 13 tools disappear from `tools/list` in one notification → sidebar shows all tools grayed out → selecting any shows "Server is disabled" in detail panel.

5. **API failure resilience**: User clicks toggle, network drops → toggle reverts to previous state → toast shows error → no stale UI state.

## Out of Scope

- Bulk enable/disable all tools for a server via UI button (future)
- Per-tool toggle confirmation dialog (future)
- Tool toggle state in the History/Replay views (future)
- Toggle state visible in `tools/call` error messages shown to end users of Claude (Shipyard returns error to Claude, Claude decides what to show)
- Keyboard shortcuts for toggling (future)

## Research Hints

- Files to study: `internal/gateway/policy.go` (persistence, enable/disable methods), `internal/web/server.go` (API routes, gateway_discover, gateway_call), `internal/web/ui/index.html` (toggleTool, toggleDetailPanelTool, updateExecuteButtonState, WebSocket handler), `internal/proxy/manager.go` (managedProxy, no toggle state here — it's in gateway)
- Patterns to look for: how `hub.Broadcast()` sends WebSocket messages, how `tools/list` response is constructed in `handleGatewayDiscover`, the `initialize` response in `handleGatewayInit`
- MCP spec: `notifications/tools/list_changed` pattern, `-32602` error code for unknown tools
- DevKB: DevKB/architecture.md (gateway pattern)

## Gap Protocol

- Research-acceptable gaps: CSS styling for disabled detail panel, toast component patterns
- Stop-immediately gaps: changes to MCP JSON-RPC error codes (must match spec exactly), changes to `notifications/tools/list_changed` payload format (must match spec)
- Max research subagents before stopping: 3

## Notes for the Agent

- The MCP spec says servers SHOULD (not MUST) send `notifications/tools/list_changed`. We treat it as MUST for Shipyard because tool toggles are the primary UX — clients need to know immediately.
- When disabling an entire server, send ONE `notifications/tools/list_changed` notification, not one per tool. The notification has no payload — it just tells the client to re-fetch `tools/list`.
- The `-32602` error code for disabled tools is deliberate: from the MCP client's perspective, a disabled tool doesn't exist. Using "Unknown tool" is correct and prevents leaking implementation details about the toggle feature.
- The current HTTP 403 approach in `gateway_call` is wrong for MCP compliance — MCP uses JSON-RPC errors, not HTTP status codes. The gateway should return a JSON-RPC error response with the standard structure.
- For the Shipyard built-in tool toggle: only remove the `is_self` guard on the toggle button rendering (line ~2167-2171 in index.html) and the `disabled` attribute. The `is_self` flag can remain for other purposes (e.g., hiding the server-level toggle on the Servers tab).
