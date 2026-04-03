---
id: SPEC-027
priority: 1
layer: 0
type: eval
status: done
after: []
prior_attempts: []
created: 2026-04-01
---

# Shipyard: HTTP Child MCP Lifecycle (Spawn + Connect)

## Problem

Shipyard can spawn child MCP processes and communicate via stdio, and it can connect to pre-running HTTP MCP servers via `connectHTTP()`. But it cannot do both together: **spawn a child process that serves HTTP, wait for it to be ready, then connect via HTTPBridge.**

This "spawn + connect" pattern is needed for MCPs that run as HTTP servers but whose lifecycle Shipyard manages (start, stop, restart, health check).

## Validated Facts (from agent research 2026-04-01)

### What EXISTS and works:

1. **`MCPTransport` enum** (MCPServer.swift:52-56) — has `.stdio`, `.streamableHTTP`, `.sse` cases
2. **`MCPServer.isHTTP`** (MCPServer.swift:131-133) — computed property, works correctly
3. **`ProcessManager.connectHTTP()`** (ProcessManager.swift:584-656) — **COMPLETE**:
   - Validates `configHTTPEndpoint`, constructs URL
   - Resolves Keychain secrets for headers
   - Creates HTTPBridge (or SSEBridge alias) based on transport
   - Calls `bridge.initialize()`, stores in `httpBridges[server.id]`
   - Sets state to `.running`
4. **`ProcessManager.disconnectHTTP()`** (ProcessManager.swift:659-683) — **COMPLETE**:
   - Gracefully disconnects bridge, removes from `httpBridges`
   - Transitions to `.idle`
5. **`ProcessManager.bridgeProtocol(for:)`** (ProcessManager.swift:55-61) — dispatches to `httpBridges` for HTTP/SSE, `bridges` for stdio
6. **`HTTPBridge`** (HTTPBridge.swift) — **COMPLETE** for POST/JSON (streamable-http):
   - `initialize()`, `callTool()`, `discoverTools()`, `disconnect()` all implemented
   - Session management (MCP-Session-Id), retry with exponential backoff
   - Thread-safe via `OSAllocatedUnfairLock`
   - **Does NOT support SSE event streams** — rejects `text/event-stream` (line 349-350)
7. **`MCPConfig`** (MCPConfig.swift) — parses `transport: "streamable-http"` and `url` field, validates correctly
8. **`MCPRegistry`** (MCPRegistry.swift:500-536) — maps config to MCPServer with correct transport and `configHTTPEndpoint`
9. **Gateway routing** (SocketServer.swift:606-665) — transport-agnostic, uses `bridgeProtocol(for:)`, works for both bridge types

### What is MISSING:

1. **`ProcessManager.start()` has NO transport branching** (lines 69-240) — always spawns Foundation.Process with stdio pipes, regardless of `server.transport`
2. **`ProcessManager.stop()` has NO HTTP cleanup** (lines 245-346) — only cancels stdio `bridges`, never touches `httpBridges`. Orphan bug.
3. **No HTTP readiness polling** — `connectHTTP()` assumes endpoint is immediately available. When spawning a child process, the HTTP port isn't ready instantly.
4. **No caller-side dispatch** — all call sites (`MainWindow`, `GatewayView`, `AutoStartManager`) call `start()` unconditionally. They don't need to change IF start() branches internally.
5. **`typealias SSEBridge = HTTPBridge`** (HTTPBridge.swift:371) — misleading name, both are POST/JSON only

## Requirements

- [ ] R1: `ProcessManager.start()` branches on `server.isHTTP` — spawns process THEN connects via HTTPBridge
- [ ] R2: After spawning an HTTP child, poll for HTTP readiness before calling `connectHTTP()` (retry with backoff, max ~5 seconds)
- [ ] R3: `ProcessManager.stop()` handles HTTP children — calls `disconnectHTTP()` then terminates the process
- [ ] R4: `ProcessManager.restart()` works for HTTP children (stop + start)
- [ ] R5: Health check works for HTTP children (can call a tool via HTTPBridge)
- [ ] R6: Existing stdio children continue to work unchanged
- [ ] R7: No changes needed to caller sites (MainWindow, GatewayView, AutoStartManager) — start()/stop() dispatch internally

## Design

### ProcessManager.start() — Add HTTP branch

At the top of `start()`, before the existing Foundation.Process spawning code:

```swift
func start(_ server: MCPServer) async throws {
    // NEW: HTTP child — spawn process then connect via HTTP
    if server.isHTTP {
        try await startHTTPChild(server)
        return
    }

    // EXISTING: stdio child — unchanged
    // ... existing 170 lines ...
}
```

### New method: startHTTPChild()

```swift
private func startHTTPChild(_ server: MCPServer) async throws {
    // 1. Spawn process (same as stdio — Foundation.Process, env, cwd)
    //    But do NOT set up stdin/stdout pipes for MCP communication
    //    Only capture stderr for logging
    let process = Foundation.Process()
    // ... configure executableURL, arguments, environment, cwd ...
    // ... capture stderr for logging ...
    try process.run()
    server.pid = process.processIdentifier

    // 2. Wait for HTTP readiness
    //    Poll the endpoint with backoff until initialize succeeds
    let maxAttempts = 10
    var lastError: Error?
    for attempt in 1...maxAttempts {
        do {
            try await connectHTTP(server)  // existing method
            return  // success
        } catch {
            lastError = error
            if attempt < maxAttempts {
                try await Task.sleep(nanoseconds: UInt64(100_000_000 * min(attempt, 5)))  // 100ms-500ms
            }
        }
    }
    // 3. If readiness times out, kill process and throw
    process.terminate()
    throw ProcessManagerError.startFailed("HTTP endpoint not ready after \(maxAttempts) attempts: \(lastError?.localizedDescription ?? "unknown")")
}
```

### ProcessManager.stop() — Add HTTP cleanup

In `stop()`, add HTTP branch before the existing stdio cleanup:

```swift
func stop(_ server: MCPServer) async {
    // NEW: HTTP child — disconnect bridge, then terminate process
    if server.isHTTP {
        await disconnectHTTP(server)  // existing method — cleans up httpBridges
        // Fall through to process termination below
    } else {
        // EXISTING: stdio cleanup — cancel bridge, close pipes
        if let bridge = bridges[server.id] {
            bridge.cancelAll()
            bridges.removeValue(forKey: server.id)
        }
        // ... existing pipe cleanup ...
    }

    // SHARED: Process termination (works for both)
    // ... existing SIGTERM/SIGKILL logic ...
}
```

### Config Format for HTTP Children

Shipyard MCPs configured in `~/.config/shipyard/mcps.json`:

```json
{
  "mcpServers": {
    "my-http-mcp": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:6277/mcp",
      "command": "python3",
      "args": ["server.py"],
      "cwd": "/path/to/my-mcp-server",
      "env": {
        "PYTHONUNBUFFERED": "1",
        "DATABASE_PATH": "/path/to/database.db"
      },
      "timeout": 30
    }
  }
}
```

Key: **both** `command`/`args` (for spawning) AND `transport`/`url` (for connecting). If `command` is present, Shipyard spawns. If `url` is present, Shipyard connects via HTTP. Both together = spawn + connect.

For manifest-discovered MCPs, the same logic: manifest declares both `command`/`args` and `transport`/`host`/`port`.

## Acceptance Criteria

- [ ] AC 1: An MCP with `transport: "streamable-http"` + `command` is spawned as a process AND connected via HTTPBridge
- [ ] AC 2: The process is NOT connected via stdio pipes — stderr is captured for logging but stdin/stdout are not used for MCP communication
- [ ] AC 3: If the HTTP endpoint isn't ready within 5 seconds after spawn, the process is killed and an error is reported
- [ ] AC 4: `stop()` on an HTTP child disconnects the HTTPBridge AND terminates the process (no orphan bridges, no zombie processes)
- [ ] AC 5: `restart()` on an HTTP child works (stop + start cycle)
- [ ] AC 6: Gateway calls (`shipyard_gateway_call`) route correctly to HTTP children via `bridgeProtocol(for:)`
- [ ] AC 7: Existing stdio MCPs (lmstudio, lmac-run, hear-me-say) are completely unaffected
- [ ] AC 8: CPU/memory monitoring still works for HTTP children (process is still tracked)
- [ ] AC 9: Health check can verify HTTP child is responsive (call a tool via HTTPBridge)
- [ ] AC 10: All existing tests pass without modification

## Context

- **Target file:** `Shipyard/Services/ProcessManager.swift` — primary changes (~50-80 lines)
- **Supporting:** `Shipyard/Services/HTTPBridge.swift` (no changes expected), `Shipyard/Models/MCPConfig.swift` (may need validation update for command+url combo)
- **Test file:** `ShipyardTests/` — add tests for HTTP child lifecycle
- **Framework:** SwiftUI, Swift 6 strict concurrency, Swift Testing (@Test, @Suite)
- **Related spec:** SPEC-SSE-001 (HTTP MCP server-side changes)

## Out of Scope

- [ ] SSE event stream parsing in HTTPBridge (HTTPBridge only supports POST/JSON, which is correct for streamable-http)
- [ ] Authentication/TLS
- [ ] Renaming `typealias SSEBridge = HTTPBridge` (cosmetic, separate cleanup)
- [ ] Adding notification support to HTTPBridge (MCPBridge has it, HTTPBridge doesn't — separate enhancement)
- [ ] UI changes (HTTP children should display the same as stdio children in the sidebar)

## Research Hints

- `ProcessManager.start()` begins at line 69 — all 170 lines are stdio-specific
- `ProcessManager.connectHTTP()` at line 584 — complete, use as-is after spawn
- `ProcessManager.disconnectHTTP()` at line 659 — complete, use for cleanup
- `ProcessManager.stop()` at line 245 — only cleans up stdio `bridges` dict, never `httpBridges`
- `MCPServer.isHTTP` at line 131 — the dispatch condition
- Caller sites (MainWindow:266, MainWindow:306, GatewayView:388, AutoStartManager:209) all call `start()` directly — they should NOT need changes
- DevKB: `swift.md`, `xcode.md`

## Gap Protocol

- Research-acceptable gaps: Exact stderr capture pattern for HTTP children, health check frequency
- Stop-immediately gaps: `connectHTTP()` doesn't actually work, HTTPBridge initialize fails against FastMCP streamable-http
- Max research subagents before stopping: 2

## Quality Metrics & Scoring Notes

### Expected Outcomes

- **Code Change Size:** ~50-80 lines in ProcessManager.swift, ~20 lines tests
- **Review Cycles:** 1-2 (Swift concurrency requires careful review)

### Pass/Fail Criteria

**PASS if:** HTTP child spawns, connects, serves gateway calls, stops cleanly. Stdio children unaffected.

**FAIL if:** Stdio children break, HTTP readiness polling doesn't converge, stop() leaves orphans.

### Notes for the Agent

- Read `DevKB/swift.md` before writing any Swift code — concurrency traps are documented there.
- `@MainActor` on `ProcessManager` means all methods are main-actor isolated. `Task.sleep` is fine.
- Do NOT modify `connectHTTP()` or `disconnectHTTP()` — they are complete and tested.
- Do NOT modify `HTTPBridge` — it already works for streamable-http.
- The new `startHTTPChild()` method should reuse process spawning patterns from existing `start()` but skip stdio pipe setup.
- Build after every change: `mcp__xcode__BuildProject`. One change at a time.
- Run existing tests after changes to verify no regressions.
- `Foundation.Process` stderr capture: use `Pipe()` on `process.standardError`, read async.
