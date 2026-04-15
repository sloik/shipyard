---
id: SPEC-028
template_version: 2
priority: 2
layer: 2
type: feature
status: done
after: []
prior_attempts: []
created: 2026-04-15
completed: 2026-04-15
---

# Tool & Server Enable/Disable Toggles

## Problem

The Go version of Shipyard (v2) has no mechanism for users to enable or disable individual tools or entire MCP servers. All discovered tools are always active and forwarded to Claude. The SwiftUI version (SPEC-002) implemented dual-level toggles (server-level + tool-level) with UserDefaults persistence and gateway filtering — this feature needs to be ported to the Go web UI and backend.

Without toggles, users cannot:
- Temporarily disable a noisy or dangerous tool without stopping the entire MCP server
- Disable an entire MCP server's tools without stopping the process (useful for testing)
- Control which tools Claude sees in the aggregated gateway tool list

## Requirements

### Backend — State Management

- [x] R1: Add `enabled` boolean field to `managedProxy` struct (server-level toggle, default: `true`)
- [x] R2: Add per-tool enabled state map to Manager (tool-level toggle, default: `true`)
- [x] R3: Persist toggle state to a JSON file (`~/.config/shipyard/toggle-state.json`)
- [x] R4: Load persisted state on startup; missing keys default to enabled
- [x] R5: Precedence logic: tool is available = `server.enabled AND (toolOverride ?? true)`

### Backend — API Endpoints

- [x] R6: `PUT /api/servers/{name}/enabled` — toggle server enabled state (body: `{"enabled": bool}`)
- [x] R7: `PUT /api/tools/{server}/{tool}/enabled` — toggle individual tool enabled state (body: `{"enabled": bool}`)
- [x] R8: `GET /api/servers` response includes `enabled` field per server
- [x] R9: `GET /api/tools` response includes `enabled` field per tool and `server_enabled` field
- [x] R10: Broadcast toggle state changes via WebSocket hub (so UI updates in real-time)

### Backend — Gateway Filtering

- [x] R11: `gateway_discover` (tool list sent to Claude) excludes disabled tools
- [x] R12: `gateway_call` for a disabled tool returns error `tool_unavailable` with message "Tool '{name}' is disabled. Enable it in the Shipyard dashboard."
- [x] R13: `gateway_call` for a tool on a disabled server returns error `server_disabled` with message "Server '{name}' is disabled. Enable it in the Shipyard dashboard."

### UI — Sidebar Tool List

- [x] R14: Each tool row in the sidebar shows a Switch toggle on the right side
- [x] R15: Tool row layout: horizontal frame, `alignItems: center`, `justifyContent: space_between`, `padding: [6, 12, 6, 32]`, `width: fill_container`. Children: `left` wrapper frame (`gap: 8`, `width: fill_container`, containing wrench icon 14×14 + tool name text) and Switch ref on the right
- [x] R16: **Enabled state**: `Switch/On` ref, icon fill `$text-muted` (or `$accent-fg` if active/selected), text fill `$text-secondary` (or `$text-primary` if active), font-weight `normal` (or `500` if active)
- [x] R17: **Disabled state**: `Switch/Off` ref, `opacity: 0.5` on the entire row, icon fill `$text-muted`, text fill `$text-secondary`, font-weight `normal`
- [x] R18: **Active/selected row** (tool currently viewed in detail panel): `fill: $row-selected` on the row frame, icon fill `$accent-fg`, text fill `$text-primary`, font-weight `500`
- [x] R19: Toggle reflects current enabled/disabled state from API
- [x] R20: Toggling calls `PUT /api/tools/{server}/{tool}/enabled` and updates UI optimistically
- [x] R21: When server is disabled, all child tool toggles show `Switch/Off` with `opacity: 0.5` and are not interactive
- [x] R22: Conflict rows (tools that exist in multiple servers) do NOT show a toggle — they show a warning icon + "also in: {server}" label instead

### UI — Server Card

- [x] R23: Server card header shows a master Switch toggle on the right side
- [x] R24: Header layout: horizontal frame, `justifyContent: space_between`, `padding: [12, 16]`, bottom border `$border-muted`. Children: `scName` frame (status dot + server name) on left, tools badge in middle, Switch ref on right
- [x] R25: Toggle reflects current enabled/disabled state from API
- [x] R26: Toggling calls `PUT /api/servers/{name}/enabled` and updates UI optimistically
- [x] R27: Disabling server visually grays out all child tool toggles in sidebar

### UI — Tool Detail Panel

- [x] R28: Tool detail panel title row shows a Switch toggle synced with the sidebar toggle for the same tool
- [x] R29: Title row layout: horizontal frame, `alignItems: center`, `justifyContent: space_between`, `width: fill_container`. Children: `left` wrapper frame (`gap: 8`, containing wrench icon 18×18 `$accent-fg` + tool name text `$font-mono` `$font-size-2xl` `600` + server badge pill) and Switch ref on the right
- [x] R30: Toggling in detail panel updates sidebar toggle and vice versa (single source of truth)
- [x] R31: When tool is disabled, the detail panel still shows the tool's schema and form but the Execute button is disabled with a "Tool disabled" hint

## Acceptance Criteria

### State Management

- [x] AC 1: `managedProxy` has `enabled` field; default `true` for new servers
- [x] AC 2: Manager maintains `toolEnabled map[string]bool` keyed by `{server}__{tool}`
- [x] AC 3: Toggle state persists to `~/.config/shipyard/toggle-state.json`
- [x] AC 4: On restart, previously disabled tools/servers remain disabled
- [x] AC 5: Missing keys in persisted state default to enabled (backward compatible)
- [x] AC 6: Precedence: disabled server → all tools disabled regardless of tool-level state

### API

- [x] AC 7: `PUT /api/servers/{name}/enabled` with `{"enabled": false}` sets server disabled; returns 200
- [x] AC 8: `PUT /api/tools/{server}/{tool}/enabled` with `{"enabled": false}` sets tool disabled; returns 200
- [x] AC 9: `GET /api/servers` includes `"enabled": true/false` per server
- [x] AC 10: `GET /api/tools` includes `"enabled": true/false` per tool and `"server_enabled": true/false`
- [x] AC 11: Toggle changes broadcast via WebSocket (`{"type": "toggle_changed", ...}`)

### Gateway Filtering

- [x] AC 12: Disabled tool is excluded from `tools/list` response sent to Claude
- [x] AC 13: Calling disabled tool returns JSON-RPC error with code `-32601` and message containing "disabled"
- [x] AC 14: Calling tool on disabled server returns JSON-RPC error with code `-32601` and message containing "disabled"
- [x] AC 15: Re-enabling a tool makes it immediately available in next `tools/list`

### UI — Layout

- [x] AC 16: Tool list sidebar rows: `left` frame (icon + name, `gap: 8`, `width: fill_container`) + Switch ref, parent has `justifyContent: space_between`, `padding: [6, 12, 6, 32]`
- [x] AC 17: Server card header: status dot + name on left, tools badge in middle, Switch ref on right, `justifyContent: space_between`, `padding: [12, 16]`
- [x] AC 18: Tool detail title row: `left` frame (icon 18px + name `font-size-2xl` + server badge) + Switch ref, `justifyContent: space_between`
- [x] AC 19: Sidebar toggle and detail panel toggle for same tool are always in sync

### UI — Enabled State

- [x] AC 20: Enabled tool row: `Switch/On` (accent fill `$accent-emphasis`, 36×20px, `cornerRadius: radius-full`), row at full opacity
- [x] AC 21: Enabled + selected tool row: `fill: $row-selected`, icon `$accent-fg`, text `$text-primary` weight `500`, `Switch/On`
- [x] AC 22: Enabled + default tool row: icon `$text-muted`, text `$text-secondary` weight `normal`, `Switch/On`

### UI — Disabled State

- [x] AC 23: Disabled tool row: `Switch/Off` (border-default fill `$border-default`, 36×20px), `opacity: 0.5` on entire row frame
- [x] AC 24: Disabled tool row text/icon colors: icon `$text-muted`, text `$text-secondary`, weight `normal` (regardless of selection)
- [x] AC 25: Disabling server sets all child tool rows to disabled visual state (`Switch/Off`, `opacity: 0.5`, not interactive)
- [x] AC 26: Disabled tool in detail panel: form visible but Execute button disabled, hint text "Tool is disabled"

### UI — General

- [x] AC 27: Switch components use design system tokens: `Switch/On` = `$accent-emphasis` fill, `Switch/Off` = `$border-default` fill, knob = `$text-on-emphasis` 16px circle
- [x] AC 28: Toggle state persists across page refresh (API-backed, not localStorage)
- [x] AC 29: Conflict rows (warning-highlighted tools in Tool Conflicts screen) do NOT show toggles — they show warning icon + conflict info instead
- [x] AC 30: Shipyard built-in server toggle is hidden or always-on (cannot disable self)

## Context

### Existing Go Code (v2/main branch)

- `internal/proxy/manager.go` — `managedProxy` struct has `status`, `command`, `toolCount` but no `enabled` field. `Manager` has `proxies map[string]*managedProxy`. Add `enabled` to `managedProxy`, add `toolEnabled` map to `Manager`.
- `internal/web/server.go` — API routes. `ProxyManager` interface has `Servers()`, `SendRequest()`, etc. Add `SetServerEnabled(name string, enabled bool)`, `SetToolEnabled(server, tool string, enabled bool)`, `IsToolEnabled(server, tool string) bool` to the interface.
- `internal/web/server.go` — `ServerInfo` struct has `Name`, `Status`, `Command`, `ToolCount`, etc. Add `Enabled bool` field.
- `internal/web/ui/index.html` — Main UI. Tool list rows, server cards, detail panel all need Switch toggle components added.
- `internal/web/ui/ds.css` — Design system CSS. Switch/toggle styles need to be added.

### SwiftUI Reference (swiftui/v0 branch)

- `Shipyard/Models/GatewayRegistry.swift` — State storage pattern: UserDefaults keys `gateway.mcp.enabled.{name}` and `gateway.tool.enabled.{prefixedName}`. Precedence at line 137-140: `mcpOn = isShipyardServerName ? true : (mcpEnabled[name] ?? true); toolOverride = toolOverrides[prefixed]; enabled = toolOverride ?? mcpOn`.
- `Shipyard/Views/GatewayView.swift` — SwiftUI Toggle for MCP-level (in server row) and tool-level (in tool row). Tool toggle disabled when server not running.
- SPEC-002 — Full spec for the SwiftUI gateway feature including enable/disable.

### Design (UX-002)

- Design file: `.nightshift/designs/UX-002-tool-browser.pen`

**Reusable components:**
- `Switch/On` (`TvVwX`): 36×20px, fill `$accent-emphasis`, `cornerRadius: radius-full`, `padding: 2`, `justifyContent: end`. Child: knob ellipse 16×16 fill `$text-on-emphasis`
- `Switch/Off` (`dc1dB`): 36×20px, fill `$border-default`, same structure as Switch/On but knob positioned at start
- `ToolList/ItemDefault` (`Ndy13`): reusable component with Switch toggle on right
- `ToolList/ItemActive` (`q2Qdq`): reusable component, `fill: $row-selected`, Switch toggle on right
- `Card/Server` (`YYMTJ`) header (`pRmbW`): Switch toggle after tools badge

**Tool row layout (all screens):**
Each tool row is a horizontal frame with: `left` child frame (`gap: 8`, `width: fill_container`, containing icon 14×14 + tool name text `$font-mono` `$font-size-base`) + Switch ref on right. Parent row: `alignItems: center`, `justifyContent: space_between`, `padding: [6, 12, 6, 32]`, `width: fill_container`.

**Enabled vs disabled visual states:**
- Enabled: `Switch/On` ref (`TvVwX`), row at full opacity (1.0)
- Disabled: `Switch/Off` ref (`dc1dB`), row `opacity: 0.5`
- Active/selected (enabled): additional `fill: $row-selected`, icon `$accent-fg`, text `$text-primary` weight `500`

**Tool detail title row layout (all detail screens):**
Horizontal frame `nXdVa`/`psIlB`/`amH1C`/`nCeUI`: `alignItems: center`, `justifyContent: space_between`, `width: fill_container`. Children: `left` frame (`gap: 8`, containing wrench icon 18×18 `$accent-fg` + tool name `$font-mono` `$font-size-2xl` `600` + server badge pill `$bg-surface` `$border-default`) + Switch ref on right.

**Screens with toggle-equipped sidebars:**
- `d1yZ4` — Phase 1: Tool Browser (sidebar `dsx1Y`, detail `nXdVa`)
- `KV32h` — Phase 1: No Tool Selected (sidebar `pnRwo`, no detail panel)
- `9KGDt` — Multi-Field Form / create_issue (sidebar `Gq6xJ`, detail `nCeUI`)
- `z3HFx` — Executing/Loading (sidebar `Uv9Az`, detail `psIlB`)
- `owML0` — Error Response (sidebar `Utzp9`, detail `amH1C`)
- `R9sUx` — Server Offline sidebar (standalone, no detail panel)

**Screens with special sidebar behavior:**
- `Mu8Pf` — Tool Conflicts: normal rows have toggles, conflict-highlighted rows (`$warning-subtle` fill) show warning icon + "also in: {server}" text instead of toggle

### Persistence Strategy

Go version uses JSON file instead of UserDefaults (macOS-only). File format:

```json
{
  "servers": {
    "filesystem": true,
    "lm-studio": false
  },
  "tools": {
    "filesystem__read_file": true,
    "filesystem__write_file": false
  }
}
```

File location: `~/.config/shipyard/toggle-state.json`. Created on first toggle change. Atomic write (write to temp file, rename).

## Scenarios

1. **Disable a single tool**: User sees 8 tools for "filesystem" server → clicks Switch toggle on `write_file` tool in sidebar → toggle flips to Off → tool disappears from Claude's tool list → user calls `write_file` via Claude → gets "tool disabled" error → user re-enables → tool available again immediately.

2. **Disable entire server**: User clicks Switch toggle on "filesystem" server card header → all 8 tool toggles gray out → tools removed from Claude's tool list → calling any filesystem tool returns "server disabled" error → user re-enables server → all previously-enabled tools come back (previously-disabled tools stay disabled).

3. **Synced toggles**: User selects `read_file` in sidebar → detail panel shows same tool with Switch On → user disables via detail panel toggle → sidebar toggle for `read_file` also flips to Off → state is consistent.

4. **Persistence across restart**: User disables `write_file` and `delete_file` → restarts Shipyard → both tools still disabled → no data loss.

5. **New tool discovered**: MCP server adds a new tool → Shipyard discovers it → tool defaults to enabled → no entry needed in toggle-state.json.

## Out of Scope

- Bulk enable/disable all tools for a server (future)
- Toggle state sync across machines (future)
- Tool groups/categories with group-level toggles (future)
- Keyboard shortcuts for toggling (future)
- Undo/redo for toggle changes (future)

## Research Hints

- Files to study: `internal/proxy/manager.go` (managedProxy struct, Manager methods), `internal/web/server.go` (API routes, ProxyManager interface, ServerInfo struct), `internal/web/ui/index.html` (UI rendering), `internal/web/ui/ds.css` (design tokens)
- Patterns to look for: how `ServerInfo` is constructed in `Servers()` method, how `handleTools` returns tool list, how WebSocket broadcasts work via `hub.Broadcast()`
- SwiftUI reference: `Shipyard/Models/GatewayRegistry.swift` lines 130-145 for precedence logic
- DevKB: DevKB/architecture.md (gateway pattern)

## Gap Protocol

- Research-acceptable gaps: Go file I/O patterns for config persistence, CSS toggle component styling
- Stop-immediately gaps: changes to ProxyManager interface signature (affects multiple callers), changes to JSON-RPC error codes (affects Claude integration)
- Max research subagents before stopping: 3

## Notes for the Agent

- The Shipyard built-in server (`is_self === true` in JS) should always be enabled and its toggle should be hidden or disabled — Shipyard cannot disable itself.
- Toggle state is API-backed, not localStorage. The UI reads state from `GET /api/servers` and `GET /api/tools` responses.
- WebSocket broadcasts ensure multiple browser tabs stay in sync.
- The Switch CSS component should match the design system: 36×20px pill with 16px round knob, transition animation on toggle.
- Atomic file writes for toggle-state.json: write to `.toggle-state.json.tmp`, then `os.Rename()` to prevent corruption on crash.
