---
id: BUG-003
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-009, SPEC-011]
prior_attempts: []
created: 2026-03-26
completed: 2026-03-26
---

# Tool Execution May Not Complete End-to-End — Queue Panel Not Updating

## Problem

When a user executes a tool (e.g., `list_voices` from hear-me-say MCP), nothing visibly happens in the UI. The execution queue panel at the bottom of the Gateway tab doesn't show the execution entry. It's unclear whether:
1. The sheet isn't calling `ExecutionQueueManager.executeToolAsync()` correctly
2. The SocketServer.callTool() extension isn't routing to the child MCP
3. The bottom panel isn't observing `ExecutionQueueManager` changes
4. The panel is collapsed or hidden by default

**Violated spec:** SPEC-009 (Tool Execution Engine) + SPEC-011 (Execution Queue Panel)
**Violated criteria:**
- SPEC-009 AC 4: "executeToolAsync() adds execution to activeExecutions, spawns a Task, and returns immediately"
- SPEC-011 AC 2: "Panel header shows execution counts"
- SPEC-011 AC 3: "Active entries show ⏳ icon, tool name, live elapsed time, timestamp"

## Requirements

- [ ] R1: Verify ToolExecutionSheet correctly calls `ExecutionQueueManager.executeToolAsync()` after user confirms
- [ ] R2: Verify `ExecutionQueueManager.socketServer` is non-nil (properly wired in ShipyardApp)
- [ ] R3: Verify `SocketServer.callTool()` correctly constructs and sends a `gateway_call` JSON-RPC request
- [ ] R4: Verify the callTool response is parsed and stored in `ToolExecution.response`
- [ ] R5: Verify the bottom panel is visible by default (not collapsed) and reads from `@Environment(ExecutionQueueManager.self)`
- [ ] R6: Add visible debug feedback: if callTool fails, the error must appear in the queue panel (not silently swallowed)

## Acceptance Criteria

- [ ] AC 1: Executing any tool from the sheet creates a visible entry in the execution queue panel
- [ ] AC 2: Active execution shows ⏳ while running, then transitions to ✓ or ✗
- [ ] AC 3: If the tool call fails (child MCP not running, bad arguments), the error is shown in the queue panel row
- [ ] AC 4: The execution queue panel is visible (not collapsed) by default on first use
- [ ] AC 5: `ExecutionQueueManager.socketServer` is non-nil when the sheet calls executeToolAsync
- [ ] AC 6: Build succeeds with zero errors; all existing tests pass

## Context

**Files to verify and potentially fix:**

1. **ToolExecutionSheet.swift** — check the Execute button action. Does it call `queueManager.executeToolAsync()`? Does it pass the correct tool name and arguments?

2. **ExecutionQueueManager.swift** — check `executeToolAsync()` and `executeInternal()`. Is the socketServer reference set? Does the Task actually run? Is the execution added to `activeExecutions` before the task starts?

3. **ShipyardApp.swift** — check that `executionQueueManager.setSocketServer(socketServer)` (or equivalent) is called during app setup

4. **SocketServer+callTool extension** — check the callTool method. Does it construct the correct JSON-RPC message? Is the tool name passed in the right format (namespaced or stripped)? Does it await the response?

5. **ExecutionQueuePanelView.swift** — check that it reads from `@Environment(ExecutionQueueManager.self)`. Is `isCollapsed` defaulting to false?

6. **GatewayView.swift** — check that `ExecutionQueuePanelView()` is actually rendered at the bottom of the view hierarchy

## Scenarios

1. User clicks ▶ on `hear-me-say__list_voices` → fills `{}` → clicks Execute → confirms → sheet closes → ⏳ entry appears in queue → completes with ✓ or ✗ within 5 seconds
2. User clicks ▶ on a Shipyard tool (`shipyard__status`) → executes with `{}` → ✓ entry in queue with response visible via [View]
3. User executes a tool on a stopped MCP → ✗ entry appears with error message "MCP not running" or similar

## Notes for the Agent

- **Read all 5 files listed in Context before making changes**
- **Trace the full call chain**: Sheet → QueueManager → SocketServer → child MCP → response → queue update
- **Common failure points:**
  - socketServer is nil (not wired)
  - callTool constructs wrong JSON-RPC format
  - Tool name needs namespace stripping (or doesn't — check what gateway_call expects)
  - Task is spawned but errors are caught silently (missing do/catch, or catch that swallows)
  - Panel exists but `@Environment` isn't injected at the right level
- **Add print() debug logging** at key points if needed: when executeToolAsync is called, when callTool sends, when response arrives
- **Build after every change**
