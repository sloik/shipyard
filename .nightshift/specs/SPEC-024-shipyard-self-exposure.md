---
id: SPEC-024
priority: 2
layer: 3
type: feature
status: done
after: [SPEC-023]
prior_attempts: []
created: 2026-03-31
completed: 2026-03-31
---

# Shipyard Self-Exposure in Gateway Tab

## Problem

Shipyard operates as an MCP server itself — listening on a Unix domain socket and exposing tools like `shipyard_status`, `shipyard_health`, `shipyard_restart`, `shipyard_gateway_discover` — but this is completely invisible in the Gateway tab (⌘2). The app shows only child MCPs in the list. Shipyard never shows itself.

Full design, data flow, architecture diagram, and ADRs: `docs/specs/006-shipyard-self-exposure.md`

## Requirements

### GatewayRegistry — Shipyard as Special Server

- [x] `GatewayRegistry` treats Shipyard as a special server distinct from child MCPs
  - Internal helper: `isShipyardServer(_ server:)` or equivalent
  - Shipyard tools stored under namespace `shipyard__{tool_name}` (same double-underscore convention)
  - Shipyard tools show first in detail view (above child MCPs)
  - See `Shipyard/Models/GatewayRegistry.swift`

- [x] Shipyard tool discovery via new `shipyard_tools` socket method
  - Called during `discoverTools()` alongside child MCP discovery
  - Returns: `shipyard_status`, `shipyard_health`, `shipyard_logs`, `shipyard_restart`, `shipyard_gateway_discover`, `shipyard_gateway_call`, `shipyard_gateway_set_enabled`
  - Response format matches child MCP tools: `name`, `description`, `input_schema`
  - Triggered on app startup and manual refresh

### SocketServer — New Method + Enforcement

- [x] New socket method `shipyard_tools` in `SocketServer.dispatchRequest`
  - Returns hardcoded array of Shipyard tool metadata (name, description, empty input_schema)
  - Called by GatewayRegistry during discovery phase
  - Returns empty array if no tools (edge case)
  - See `ShipyardBridgeLib/SocketServer.swift`

- [x] `gateway_call` enforces Shipyard tool enabled state
  - Before routing a `shipyard__{tool_name}` call, check if tool is enabled in UserDefaults
  - Return `tool_unavailable` error if disabled
  - Existing child MCP routing unaffected

### Enable/Disable State

- [x] Per-tool enable/disable for Shipyard tools persisted to UserDefaults
  - Key format: `shipyard.tool.shipyard.{tool_name}.enabled`
  - Default: `true` if key doesn't exist (all tools enabled out of the box)
  - `gateway_set_enabled` extended to handle `shipyard__{tool_name}` targets
  - No MCP-level toggle for Shipyard (it's always running; disabling it would break the gateway)

### Gateway UI

- [x] New `ShipyardStatusCard` SwiftUI component
  - Shows: title "Shipyard", green status indicator (always running), uptime since app launch
  - Buttons: [Restart socket listener] and [Logs] (Restart can be a no-op stub for MVP)
  - Visually distinct from child MCP cards (different background, border, or card styling)
  - See `Shipyard/Views/GatewayView.swift` for placement context

- [x] `GatewayView` renders Shipyard first, then child MCPs
  - `ShipyardStatusCard` at the top of the detail pane
  - Shipyard tool list below the card (same row component as child MCP tools)
  - Tools displayed without `shipyard__` prefix (show "status", "health", etc.)
  - Each tool row has enable/disable toggle
  - Disabled tools: grayed-out toggle, same as child MCP disabled tools

- [x] Real-time updates
  - Toggling a Shipyard tool in UI updates `GatewayRegistry` and UserDefaults immediately
  - UI reflects new state without manual refresh

### Tests

- [x] Unit tests in `ShipyardTests/` or `ShipyardBridgeTests/`:
  - `GatewayRegistry`: Shipyard server detection, tool namespace handling (`shipyard__toolname`), UserDefaults read/write
  - `SocketServer`: `shipyard_tools` method returns correct tools; `gateway_call` rejects disabled Shipyard tools
  - Enable/disable: default state (all enabled), toggle persists, re-enable restores availability

- [x] Build succeeds with zero errors; all existing tests pass

## Implementation Order

1. `shipyard_tools` socket method + `GatewayRegistry` Shipyard abstraction (discovery, namespacing)
2. Enable/disable state: UserDefaults storage + `gateway_call` disabled-tool guard
3. `ShipyardStatusCard` component + `GatewayView` changes
4. Unit tests for all new logic

## Key Files

- `Shipyard/Models/GatewayRegistry.swift` — add Shipyard server detection, tool storage
- `ShipyardBridgeLib/SocketServer.swift` — add `shipyard_tools` method, enforce disabled-tool guard
- `Shipyard/Views/GatewayView.swift` — render `ShipyardStatusCard` above child MCP list
- `Shipyard/Views/ShipyardStatusCard.swift` — new component (create this file)
- `ShipyardTests/GatewayRegistryTests.swift` — new tests
- `ShipyardTests/SocketServerTests.swift` or `ShipyardBridgeTests/` — new tests

## References

- Full design spec: `docs/specs/006-shipyard-self-exposure.md`
- Gateway pattern: `docs/specs/002-gateway.md`, `.nightshift/specs/SPEC-002-gateway.md`
- Enable/disable pattern: `docs/specs/002-gateway.md` § Enable/Disable State Management
