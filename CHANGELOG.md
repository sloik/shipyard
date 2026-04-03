# Shipyard Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

#### SPEC-006: Expose Shipyard as First-Class Managed MCP Server (Gateway Tab)
- **Socket Server**: Implemented `shipyard_tools` method to expose all Shipyard tools with metadata
  - Returns hardcoded list of 6 Shipyard tools: status, health, logs, restart, gateway_discover, gateway_call
  - Each tool includes name, description, and input schema
  - Implemented `handleShipyardToolCall()` to route Shipyard tool invocations to existing handlers
- **Gateway Registry**: Added Shipyard-specific tool state management
  - Added `shipyardToolEnabledPrefix = "shipyard.tool.shipyard."` constant for persistence keys
  - Implemented `isShipyardServer()` helper to identify Shipyard vs child MCPs
  - Updated `setToolEnabled()` to use special key format for Shipyard tools
  - Updated `loadPersistedState()` to handle Shipyard tool state loading
- **Gateway View**: Added Shipyard status card to Gateway tab
  - Displays Shipyard as special status card above child MCP list
  - Shows "Running" status indicator and uptime
  - Renders Shipyard tools with enable/disable toggles
  - Modified `discover()` to populate Shipyard tools before child MCPs
  - Shipyard tools displayed without `shipyard__` prefix in UI for readability
- **Tool Availability**: Disabled Shipyard tools now return `tool_unavailable` error when invoked
- **Unit Tests**: Added 3 new tests to GatewayRegistryTests.swift
  - `shipyardToolsAreRecognized()`: Verifies `isShipyardServer("shipyard")` returns true
  - `shipyardToolPersistenceUsesCorrectKeyFormat()`: Verifies state persistence with correct UserDefaults keys
  - `shipyardToolsDontHaveMCPLevelDisable()`: Verifies Shipyard remains enabled at MCP level

### Changed

- Socket Server: Modified `gateway_call` error response to return `tool_unavailable` error code for disabled tools (instead of descriptive message)
- Gateway Registry: Enhanced enable/disable logic to support Shipyard's special key format while maintaining child MCP patterns

### Technical Details

- **Acceptance Criteria**: All 15 ACs from SPEC-006 are fully addressed:
  - AC1-3: Shipyard recognized as special server with namespaced tools
  - AC4-5: Tool state persists to UserDefaults with correct key format
  - AC6-11: UI displays Shipyard card with status, tools, and toggles
  - AC12-15: Tool availability enforced, state persists across app restart, discovery handles Shipyard integration
- **Key Pattern**: Shipyard tools use `shipyard__` prefix in registry (matching child MCP convention) but display without prefix in UI
- **Default Behavior**: All Shipyard tools enabled by default; UserDefaults absence defaults to true
- **Real-time Updates**: GatewayRegistry publishes state changes immediately; GatewayView observes and refreshes
- **Backward Compatibility**: Graceful degradation if `shipyard_tools` method unavailable; treats as empty list

## Previous Versions

(See git history for earlier releases)
