---
id: BUG-008
priority: 2
layer: 1
type: bugfix
status: done
after: [SPEC-009]
violates: [SPEC-009]
prior_attempts: []
created: 2026-03-26
---

# MCP Tool Response Not Logged in Debug Output

## Problem

When a tool is executed via the Gateway tab, the debug logs show the request being sent and that a response was received, but the actual response content is never logged. This makes debugging tool execution issues impossible without stepping through in a debugger.

The MCP bridge logs (visible in the Servers tab LogViewer) show `tools/call: list_voices done` but not what was returned. The ExecutionQueueManager logs "Execution succeeded" but not the response payload.

**Violated spec:** SPEC-009 (Tool Execution Engine) — implicit NFR: execution flow should be debuggable
**Violated criteria:** Debug logging should include enough information to diagnose tool execution issues

## Reproduction

1. Open Gateway tab → execute any tool (e.g., `hear-me-say__list_voices`)
2. Check Xcode console / System Logs tab
3. **Actual logs:**
   ```
   callTool: dispatching gateway_call for tool hear-me-say__list_voices
   callTool: received response for hear-me-say__list_voices
   Saved recent call for hear-me-say__list_voices
   Execution succeeded: hear-me-say__list_voices (id=...)
   ```
4. **Missing:** The actual response content or at least its size/summary
5. **Expected:** At minimum, log the response size. Optionally log a truncated preview of the response content.

## Root Cause

In `ExecutionQueueManager.swift`, the `executeInternal` method (lines 78-109) receives `responseJSON` from `socketServer.callTool()` but only logs the tool name on success (line 101). The response content is never logged.

In the `SocketServer.callTool()` extension (lines 201-222), the response from `dispatchRequest()` is returned but only `"received response"` is logged (line 218).

## Requirements

- [ ] R1: Log the response size (character count) after successful tool execution
- [ ] R2: Log a truncated preview of the response (first 200 chars) at debug level
- [ ] R3: Log the full response at a lower log level (or behind a verbose flag) for detailed debugging
- [ ] R4: Log error responses with full error detail

## Acceptance Criteria

- [ ] AC 1: After executing a tool, the debug log includes the response size (e.g., "Response: 1234 chars")
- [ ] AC 2: A truncated preview of the response is visible in debug output
- [ ] AC 3: Error responses are logged with the full error message
- [ ] AC 4: Logging doesn't impact performance (no pretty-printing in the log path)
- [ ] AC 5: Build succeeds with zero errors; all existing tests pass

## Context

**Key files:**
- `Shipyard/Models/ExecutionQueueManager.swift` — `executeInternal()` (line 87-109), `SocketServer.callTool()` extension (line 201-222)
- Logger category: `ExecutionQueueManager` (os.Logger)

**Fix approach:**

In `executeInternal()`, after receiving `responseJSON` (line 90):
```swift
let responseJSON = try await socketServer.callTool(...)
log.debug("callTool response for \(execution.toolName): \(responseJSON.count) chars")
if responseJSON.count <= 500 {
    log.debug("callTool response content: \(responseJSON)")
} else {
    log.debug("callTool response preview: \(String(responseJSON.prefix(200)))...")
}
```

In `SocketServer.callTool()` extension, after receiving `responseLine` (line 218):
```swift
log.debug("callTool: received response for \(name) (\(responseLine.count) chars)")
```

## Out of Scope

- Structured logging (AppLogger) for tool execution — that's a separate feature
- Response content indexing or search in logs
- Log level configuration UI

## Notes for the Agent

- **Read DevKB/swift.md** before coding
- Use `os.Logger` (already imported in both files) — NOT print statements
- Keep log messages concise — they show in Xcode console
- The `log.debug()` level is appropriate — these are development-time diagnostics
- Don't log at `.info` or `.warning` — response content is expected, not an issue
- **Build after every change** — zero errors required
