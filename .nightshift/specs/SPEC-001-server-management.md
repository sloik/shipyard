---
id: SPEC-001
priority: 1
layer: 0
type: feature
status: done
after: []
prior_attempts: []
created: 2026-03-16
---

# Shipyard Server Management

## Problem

Shipyard is a native macOS SwiftUI application for managing local MCP (Model Context Protocol) servers. Without unified server management, users must manually start/stop processes and have no visibility into their state, health, or resource usage. The Server Management feature provides a complete solution: process lifecycle control, real-time observability, and a gateway pattern that bridges the native UI to multiple child MCP processes.

This is the foundational layer enabling all other Shipyard functionality.

## Requirements

- [x] Discover and maintain an authoritative registry of MCP servers from manifest files
- [x] Implement complete process lifecycle management (start, stop, restart with timeout handling)
- [x] Monitor server health through periodic health checks and timeouts
- [x] Validate runtime dependencies before process launch
- [x] Securely manage and inject secrets from macOS Keychain
- [x] Implement three-channel logging (stdout, stderr, structured) with circular buffers
- [x] Monitor CPU and memory resource usage in real-time
- [x] Provide integrated UI views for server state, logs, and controls
- [x] Handle all error cases gracefully with detailed diagnostics

## Acceptance Criteria

- [x] AC 1: MCPRegistry discovers manifests at `_Tools/mcp/*/manifest.json`, parses valid JSON, skips invalid ones with warnings
- [x] AC 2: ProcessManager.start() validates dependencies, injects secrets, launches process, creates MCPBridge, routes logs
- [x] AC 3: ProcessManager.stop() sends SIGTERM, waits 5s, sends SIGKILL if timeout, cleans up pipes and bridge
- [x] AC 4: ProcessManager.restart() stops then starts process with brief delay between operations
- [x] AC 5: HealthChecker periodically invokes health_check tool (30s interval), updates healthStatus independent of processState
- [x] AC 6: DependencyChecker validates binary existence and version patterns (semantic versioning, regex parsing)
- [x] AC 7: KeychainManager stores secrets with service `com.inwestomat.shipyard`, retrieves at startup, never logs secret values
- [x] AC 8: LogBuffer maintains three separate circular buffers (1000 lines default), interleaves by timestamp, prevents unbounded memory
- [x] AC 9: ResourceStats tracked every 2 seconds while running (PID, CPU %, memory %, uptime)
- [x] AC 10: UI displays server state (idle/starting/running/stopping/error), resource stats, health status, recent logs with filtering by channel
- [x] AC 11: All error paths tested: missing dependencies, missing secrets, binary not found, permission denied, pipe failures
- [x] AC 12: All major workflows tested end-to-end: app startup, user starts/stops/restarts server, health check runs, registry refreshes

## Context

**Core Models:**
- `Shipyard/Models/MCPManifest.swift` — static server configuration from manifest.json
- `Shipyard/Models/MCPServer.swift` — runtime server state (processState, logs, health, resources)

**Service Components:**
- `Shipyard/Services/MCPRegistry.swift` — discovers and maintains registry of available servers
- `Shipyard/Services/ProcessManager.swift` — manages process lifecycle, pipes, MCPBridge creation
- `Shipyard/Services/HealthChecker.swift` — periodic health validation via MCP tool invocation
- `Shipyard/Services/DependencyChecker.swift` — validates runtime dependencies before launch
- `Shipyard/Services/KeychainManager.swift` — secure secret storage and injection

**UI Views:**
- `Shipyard/Views/MainWindow.swift` — primary app window with server list
- `Shipyard/Views/MCPRowView.swift` — per-server card with state, controls, logs, resource stats
- `Shipyard/Views/LogViewer.swift` — scrollable log display with channel filtering

**Other Models:**
- LogBuffer (circular three-channel buffer) — defined within or alongside MCPServer
- ProcessState enum — idle, starting, running, stopping, error(String)
- HealthStatus enum — healthy, unhealthy, unknown
- ResourceStats struct — pid, cpuPercent, memoryBytes, memoryPercent, uptime

**Key Design Decisions:**
- Scan is synchronous at app startup, refresh is async and cancellable (ADR 0001 — Native Swift)
- Mandatory three-channel logging: stdout, stderr, structured (ADR 0004)
- No @Environment in Commands/Service structs — explicit dependency injection (ADR 0005)
- Manifest-driven configuration — servers defined by manifest.json, not hardcoded
- Secrets stored exclusively in macOS Keychain, never logged
- One MCPBridge per running server, created at start, destroyed at stop (ADR 0002)

**Test Coverage:** ~109 tests across MCPRegistry, ProcessManager, HealthChecker, DependencyChecker, KeychainManager, LogBuffer, and integration flows (Sessions 26–53)

## Alternatives Considered

1. **This spec (native Swift):** Chosen. Rationale: tight macOS integration (Keychain, process management, UI responsiveness), no external dependencies, full control over lifecycle. Trade-off: more code than Python/shell wrapper, but justified by native UX and maintainability.

2. **Python-based daemon:** Rejected. Rationale: loose coupling with UI (harder to debug), dependency management complexity, slower startup, thread-safety issues in Python asyncio + NSProcess interaction.

3. **Single health_check status across all servers:** Rejected. Rationale: health status is orthogonal to process state — a running process can be unhealthy (e.g., resource exhaustion). Separation allows independent UI indication.

## Scenarios

1. **User opens Shipyard → sees server list with manifests discovered**
   - App startup calls MCPRegistry.scan() synchronously
   - UI displays servers in idle state
   - HealthChecker.startPeriodicChecks() timer begins (30s interval)
   - No servers running yet

2. **User clicks Start on a server → process launches with secrets injected**
   - UI calls ProcessManager.start(server)
   - DependencyChecker.checkDependencies() validates Python version
   - KeychainManager.injectSecrets() retrieves OPENAI_API_KEY from Keychain
   - NSProcess launches with merged environment
   - Pipes created, captureStdout/captureStderr tasks start
   - MCPBridge created for stdio communication
   - monitorResources() begins polling CPU/memory
   - UI updates to green indicator, shows PID, logs flow in real-time

3. **Health check runs while server is running → healthStatus updates independently**
   - Every 30s, HealthChecker.checkHealth() invokes health_check.tool (e.g., "ping")
   - Tool succeeds within 5s timeout → healthStatus = .healthy, green indicator in UI
   - Tool fails or times out → healthStatus = .unhealthy, orange/red indicator
   - processState remains .running (process is still alive, just unhealthy)
   - User can investigate logs, then stop/restart if needed

4. **User clicks Stop → process gracefully shuts down or forcibly killed**
   - UI calls ProcessManager.stop(server, timeout: 5)
   - SIGTERM sent to process
   - Poll isRunning in 0.1s intervals for up to 5 seconds
   - If exited cleanly → pipes closed, MCPBridge destroyed, state = .idle (done in ~100ms)
   - If timeout → SIGKILL sent, process forcibly terminated, cleanup completes
   - UI shows gray indicator, no PID, resource stats cleared

5. **User restarts a server → stop + start with brief delay**
   - UI calls ProcessManager.restart(server)
   - stop() completes (SIGTERM → SIGKILL path)
   - 100ms delay
   - start() called — full dependency check, secret injection, process launch
   - UI transitions: green → gray → green with fresh logs

6. **New manifest added to disk → user refreshes registry**
   - User adds new manifest.json to _Tools/mcp/my-new-server/
   - UI "Refresh" button clicked
   - MCPRegistry.scan() walks filesystem again, parses new manifest
   - UI updates to show new server in idle state
   - Running servers are unaffected

7. **Process crashes or becomes unhealthy → logs and status help user diagnose**
   - Process exits abnormally (segfault, unhandled exception)
   - captureStderr logs crash output to LogBuffer and OSLog
   - Health check timeout on next cycle → healthStatus = .unhealthy
   - UI shows error indicator, user scrolls logs, sees crash reason
   - User investigates manifest, fixes bug, clicks Restart

## Exemplar

- **Source:** macOS Process Management (NSProcess, Pipes) — standard Foundation APIs
- **What to learn:** Proper pipe handling (non-blocking read loops), SIGTERM/SIGKILL sequencing, environment variable injection
- **What NOT to copy:** Don't use Process.Communication (macOS 12.0+) for stdio — use Pipes for compatibility and explicit control over log routing

## Out of Scope

- **Process restart policies** (auto-restart on crash, max retries, retry delay) — future feature, manifest could extend with `restart_policy` config
- **Resource limits enforcement** (kill process if CPU >80%, memory >1GB) — future feature, would require cgroups or XPC service
- **Pre/post hooks** (setup.sh before start, cleanup.sh before stop) — future feature, would add manifest `hooks` object
- **Per-server Keychain service** — future feature; currently all servers use single `com.inwestomat.shipyard` service
- **Advanced filtering/search** in server list — future polish
- **Persistent log export** — LogBuffer is in-memory only; persistent logs go to OSLog and Console.app
- **Custom health check implementations** (webhook, TCP ping, shell script) — only MCP tool invocation supported currently

## Notes for the Agent

- **Manifest parsing:** MCPManifest conforms to JSON schema — `name`, `version`, `command`, `args` are required; everything else optional. Invalid manifests logged as warnings, skipped gracefully.
- **Process working directory:** Set to the directory containing manifest.json (manifest.workingDirectory computed property).
- **Environment merge:** Plain env vars from manifest.env merged with secrets from KeychainManager.injectSecrets(). Secrets always take precedence.
- **Pipe handling:** Pipes are created with default OS buffers. If child writes faster than capture tasks read, write blocks (backpressure acceptable). No non-blocking I/O needed — async tasks handle blocking naturally.
- **Resource monitoring:** CPU and memory stats come from process inspection. If process manager doesn't support it, resourceStats is nil (optional).
- **Health check timeouts:** Default 10s, configurable per server in manifest.health_check.timeout. Timeout returns .unhealthy, doesn't block other checks (all run in parallel).
- **LogBuffer capacity:** 1000 lines per channel by default. When full, oldest entry discarded (circular buffer). Configure via app preferences (future).
- **Testing patterns:** Use dependency injection for ProcessManager, HealthChecker, MCPRegistry in UI views. Mock these in tests. See existing test structure in Sessions 26–53.
- **Error logging:** All errors from start/stop/dependency check logged to OSLog with subsystem `com.inwestomat.shipyard.server`. User sees summary in UI, full details in Console.app.
- **ADR references:** ADR 0001 (Native Swift), ADR 0002 (MCPBridge), ADR 0004 (Three-Channel Logging), ADR 0005 (No @Environment in Commands).

## Completeness Checklist

- [x] MCPRegistry — discovery and maintenance of available servers
- [x] MCPManifest model — static configuration from manifest.json
- [x] MCPServer model — runtime state (process, logs, health, resources)
- [x] ProcessManager — start, stop, restart, pipe capture, resource monitoring
- [x] HealthChecker — periodic health validation via MCP tool invocation
- [x] DependencyChecker — pre-flight validation of binary and version requirements
- [x] KeychainManager — secure secret storage and injection from macOS Keychain
- [x] LogBuffer — three-channel circular logging (stdout, stderr, structured)
- [x] UI integration (MainWindow, MCPRowView, LogViewer) — display state, controls, logs
- [x] Error handling — startup errors, runtime errors, health check errors with user-friendly messaging
- [x] ~109 unit and integration tests covering all major components and workflows
- [x] Configuration defaults (scan directory, health check interval, process stop timeout, log buffer size)
- [x] Security considerations (secret handling, manifest trust, process isolation, pipe buffer overflow)
- [x] Manifest JSON schema documented with examples
