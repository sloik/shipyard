---
id: SPEC-009
priority: 1
layer: 0
type: feature
status: ready
after: [SPEC-008]
prior_attempts: []
created: 2026-03-26
---

# Tool Execution Engine — Data Model & Async Execution

## Problem

Shipyard can discover and display tools from child MCPs and itself, but cannot **execute** them. There is no data model for tool executions, no queue management, and no async call pathway from the UI to child MCP tools via SocketServer. This spec builds the foundation layer that all UI specs depend on.

## Requirements

- [ ] R1: `ToolExecution` model — represents a single tool call with status lifecycle (pending → executing → success/failure)
- [ ] R2: `ToolExecutionRequest` — captures tool name + JSON arguments payload
- [ ] R3: `ToolExecutionResponse` — captures raw JSON response string + content length
- [ ] R4: `ExecutionQueueManager` — `@Observable @MainActor` class managing active executions and history
- [ ] R5: `ExecutionQueueManager.executeToolAsync()` — creates execution, fires async task, returns immediately (non-blocking)
- [ ] R6: `SocketServer.callTool(name:arguments:)` — new async method that routes a tool call to the correct child MCP via the existing gateway_call pathway
- [ ] R7: Executions move from `activeExecutions` to `history` on completion/failure
- [ ] R8: History capped at 20 entries (oldest evicted on overflow)
- [ ] R9: Recent calls persistence — last 5 payloads per tool saved to UserDefaults, keyed by `execution.recent.{mcp}__{tool}`
- [ ] R10: `ExecutionQueueManager` injected into SwiftUI environment from ShipyardApp
- [ ] R11: Cancellation support — `ToolExecution` holds a `Task` reference; `cancel()` method sets status to `.cancelled`
- [ ] R12: Confirmation flow — `ExecutionQueueManager` does NOT auto-execute; caller must explicitly call `confirmAndExecute(execution:)` after user confirms in the sheet

## Acceptance Criteria

- [ ] AC 1: `ToolExecution` has properties: id (UUID), toolName (String), request, status, startedAt, completedAt, response, error, elapsedSeconds (computed)
- [ ] AC 2: `ExecutionStatus` enum has cases: pending, executing, success, failure, cancelled
- [ ] AC 3: `ExecutionQueueManager` is `@Observable @MainActor` with `activeExecutions` and `history` arrays
- [ ] AC 4: `executeToolAsync()` adds execution to `activeExecutions`, spawns a `Task`, and returns the execution object immediately
- [ ] AC 5: On success, execution moves to `history` with `.success` status and populated `response`
- [ ] AC 6: On failure, execution moves to `history` with `.failure` status and populated `error` string
- [ ] AC 7: `history` never exceeds 20 entries; oldest are evicted
- [ ] AC 8: `SocketServer.callTool()` is an `async throws` method that sends a tool call and returns the raw JSON response
- [ ] AC 9: `callTool()` routes through the existing gateway_call dispatch path (reuses `dispatchRequest` or similar)
- [ ] AC 10: `retryExecution()` creates a new execution with the same request and runs it
- [ ] AC 11: `cancel()` cancels the underlying Task and sets status to `.cancelled`
- [ ] AC 12: Recent calls are persisted to UserDefaults as `[[String: Any]]` (array of serialized payloads per tool)
- [ ] AC 13: `getRecentCalls(for toolName: String) -> [ToolExecutionRequest]` returns last 5 saved payloads
- [ ] AC 14: `ExecutionQueueManager` is injected via `.environment()` in ShipyardApp
- [ ] AC 15: Build succeeds with zero errors; all existing tests pass
- [ ] AC 16: New unit tests cover: execute → success flow, execute → failure flow, history cap, recent calls persistence, cancellation

## Context

**Key Files (read ALL before coding):**

### SocketServer.swift — Add callTool method
- Find the `dispatchRequest` method — this is where all socket methods are routed
- Find how `shipyard_gateway_call` is handled — the new `callTool` method should reuse this pathway
- The method needs to be `async throws` since it makes a socket call to a child MCP

### GatewayRegistry.swift — Tool metadata
- `GatewayTool` struct holds tool name, description, inputSchema
- Tools are namespaced as `{mcp}__{tool}` — the callTool method receives this namespaced name
- Check how `toolCatalog()` returns tools — this is the schema source for the form UI

### ShipyardApp.swift — Environment injection point
- Add `@State var queueManager = ExecutionQueueManager()`
- Inject via `.environment(queueManager)` on the root view
- Pass `socketServer` reference to queueManager during init or setup

### MCPServer.swift / ProcessManager.swift — Child MCP communication
- Understand how child MCP tools are actually invoked (stdin/stdout JSON-RPC?)
- The `callTool` method wraps this existing call pattern

## Implementation Strategy

1. **Create model files first:**
   - `Models/ToolExecution.swift` — execution model + status enum
   - `Models/ToolExecutionRequest.swift` — request struct (Codable)
   - `Models/ToolExecutionResponse.swift` — response struct
   - `Models/ExecutionQueueManager.swift` — queue manager

2. **Add `callTool` to SocketServer:**
   - Wrap the existing `gateway_call` handling in an async method
   - Return raw JSON string as response
   - Throw on error (timeout, MCP not running, tool not found)

3. **Wire up environment injection:**
   - Add `ExecutionQueueManager` as `@State` in ShipyardApp
   - Inject into environment

4. **Write unit tests:**
   - Test execution lifecycle (pending → executing → success/failure)
   - Test history cap
   - Test recent calls persistence
   - Test cancellation

## Design Reference

→ See: `docs/specs/009-tool-execution/shipyard-execution-queue-design.md` § "Execution Queue Data Model"
→ See: `docs/specs/009-tool-execution/shipyard-execution-architecture.md` § "Threading model"

## Out of Scope

- UI components (covered by SPEC-010, SPEC-011, SPEC-012)
- JSON syntax highlighting (SPEC-012)
- Parameter form generation (SPEC-010)
- Bottom panel UI (SPEC-011)

## Notes for the Agent

- **Read existing SocketServer.swift thoroughly** — understand the dispatch pattern before adding callTool
- **`@MainActor` everywhere** — ExecutionQueueManager and ToolExecution must be MainActor to work with SwiftUI
- **Do NOT use completion handlers** — use async/await throughout
- **Do NOT guess API names** — grep the codebase for existing patterns (dispatchRequest, gateway_call handling)
- **AnyCodable may not exist** — check if there's already a JSON value type in the project. If not, use `[String: Any]` with JSONSerialization, or define a simple `JSONValue` enum
- **New .swift files MUST be added via `mcp__xcode__XcodeWrite`** — writing to disk alone won't register them in xcodeproj
- **Build after every change** — zero errors required
- **Run existing tests after every change** — they must still pass
