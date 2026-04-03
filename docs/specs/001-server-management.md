# Shipyard Server Management — Specification

> **Version:** 1.0
> **Author:** AI assistant
> **Date:** 2026-03-16
> **Methodology:** Spec-driven development — change this specification before changing tests or code.
> **Status:** Accepted (fully implemented, ~109 tests across Sessions 26–53)

---

## 1. Goal and Philosophy

Shipyard is a native macOS SwiftUI application for managing local MCP (Model Context Protocol) servers. The Server Management feature provides unified lifecycle control, runtime observability, and a gateway pattern that bridges the native UI to multiple child MCP processes.

**Three core responsibilities:**
1. **Discovery:** Scan the local filesystem for MCP server manifests and maintain an authoritative registry
2. **Lifecycle:** Start, stop, and restart server processes with proper dependency validation, secret injection, and error handling
3. **Observability:** Monitor process state, health, resource usage, and logs in real-time, exposing this state to the UI

**Design principles:**
- Native Swift (ADR 0001) — no Python, Electron, or external dependencies for core functionality
- Mandatory three-channel logging (ADR 0004) — stdout, stderr, and structured logs separated
- No @Environment in Commands structs (ADR 0005) — explicit dependency injection for testability
- Manifest-driven configuration — servers are defined by `manifest.json` files, not hardcoded
- Secure by default — secrets stored in macOS Keychain, environment variable injection sanitized

---

## 2. Core Components

### 2.1 MCPRegistry

**Purpose:** Discovers and maintains the authoritative list of available MCP servers.

**Responsibilities:**
- Scan configured directories for `manifest.json` files (pattern: `_Tools/mcp/*/manifest.json`)
- Parse manifests and validate structure (name, version, command, args, env, dependencies)
- Maintain in-memory registry of MCPManifest objects
- Expose server list to UI and other components
- Refresh registry on request (e.g., when new manifest files are added)

**Key decisions:**
- Scan is synchronous and blocking during app startup; refresh is async and cancellable
- Registry does not validate that command binaries exist (validation deferred to ProcessManager)
- Manifest parsing failures are reported as warnings, not fatal errors — invalid manifests are skipped

### 2.2 MCPManifest Model

**Purpose:** Represents the static configuration of an MCP server from its `manifest.json` file.

**Properties:**
```
name: String                          // e.g., "mac-runner"
version: String                       // e.g., "1.0.0"
command: String                       // e.g., "python"
args: [String]                        // e.g., ["-m", "mcp.server.stdio"]
env: [String: String]?                // plain env vars (optional)
env_secret_keys: [String]?            // keys to inject from Keychain (optional)
dependencies: [DependencySpec]?       // runtime version requirements (optional)
health_check: HealthCheckSpec?        // tool to call for health validation (optional)
logging: LoggingSpec?                 // log level, structured format (optional)
install: InstallSpec?                 // install/setup instructions (optional)
```

**Derived properties (computed):**
```
fullPath: URL                         // path to the manifest.json file
workingDirectory: URL                 // parent directory of manifest.json
```

**Key decisions:**
- `env` and `env_secret_keys` are separated so secrets are never logged or displayed in the UI
- `args` is a flat string array, not a shell command — no shell injection risk
- Optional fields allow minimal manifests (command + args only)

### 2.3 MCPServer Model

**Purpose:** Represents the runtime state of a server instance.

**Properties:**
```
manifest: MCPManifest                 // static config (read from manifest.json)
processState: ProcessState            // idle, starting, running, stopping, error
process: Process?                     // the actual NSProcess instance (if running)
pid: Int32?                           // process ID (populated when running)
lastError: Error?                     // last error encountered (cleared on successful start)
logBuffer: LogBuffer                  // recent stdout/stderr/structured logs
healthStatus: HealthStatus            // healthy, unknown, unhealthy (from last check)
lastHealthCheck: Date?                // timestamp of last health check
resourceStats: ResourceStats?         // CPU, memory usage (if running)
```

**ProcessState enum:**
```
case idle                             // not running
case starting                         // transitioning to running
case running                          // process active
case stopping                         // transitioning to idle
case error(String)                    // failed to start, see lastError
```

**HealthStatus enum:**
```
case healthy                          // health check passed
case unhealthy                        // health check failed
case unknown                          // not checked yet, or check timed out
```

**ResourceStats struct:**
```
pid: Int32
cpuPercent: Double                    // 0-100
memoryBytes: UInt64
memoryPercent: Double                 // 0-100
uptime: TimeInterval                  // seconds since process start
```

**Key decisions:**
- Single `lastError` field replaces detailed error enum — full error details logged to console
- `logBuffer` is a circular buffer of recent lines, not the full history (bounded memory)
- `resourceStats` is optional because not all process managers can provide it
- Health status is orthogonal to process state — a running process can be unhealthy

### 2.4 ProcessManager

**Purpose:** Manages server process lifecycle: start, stop, restart, signal handling, and resource monitoring.

**Responsibilities:**
- Create and configure NSProcess instances with proper environment (secrets + plain env vars)
- Launch processes in the server's working directory
- Manage subprocess stdout/stderr pipes and route to LogBuffer
- Track process state transitions
- Implement stop and restart with configurable timeouts
- Monitor CPU and memory usage (if process manager supports it)
- Create MCPBridge instance for each running server (child process gateway)

**Key methods:**
```
func start(server: MCPServer) async throws
// 1. Run DependencyChecker (blocking)
// 2. Run KeychainManager.inject() to get secret env vars
// 3. Create NSProcess with merged environment
// 4. Set working directory
// 5. Create pipes for stdout/stderr
// 6. Launch process
// 7. Create MCPBridge for the child
// 8. Update server state to .running

func stop(server: MCPServer, timeout: TimeInterval = 5) async throws
// 1. Send SIGTERM to process
// 2. Wait for graceful shutdown (up to timeout)
// 3. If timeout exceeded, send SIGKILL
// 4. Clean up pipes and MCPBridge
// 5. Update server state to .idle

func restart(server: MCPServer) async throws
// 1. Call stop()
// 2. Call start()

func monitorResources(server: MCPServer) async
// Periodic task (every 2 seconds while running)
// Updates server.resourceStats with current CPU/memory

func captureStdout(pipe: Pipe, to: LogBuffer) async
// Read from pipe, forward to LogBuffer, accumulate for batched logging

func captureStderr(pipe: Pipe, to: LogBuffer) async
// Same as captureStdout, but marked as stderr channel
```

**Key decisions:**
- Process creation is synchronous (blocks UI briefly); async wrapper for callers
- Timeout-based stop: SIGTERM → wait → SIGKILL — avoid zombie processes
- Resource monitoring runs in background, doesn't block lifecycle operations
- Each server gets one MCPBridge — bridge created at start, destroyed at stop

### 2.5 HealthChecker

**Purpose:** Periodically validate that running servers are healthy and responsive.

**Responsibilities:**
- Maintain a periodic timer (configurable interval, default 30s)
- For each running server with a health_check defined in its manifest, invoke the MCP tool
- Capture tool result (success → healthy, error/timeout → unhealthy)
- Update server.healthStatus and server.lastHealthCheck
- Log results with structured logging
- Handle timeouts gracefully (don't block other checks)

**Key methods:**
```
func startPeriodicChecks(interval: TimeInterval = 30)
// Start background timer, check all servers

func checkHealth(server: MCPServer) async -> HealthStatus
// 1. If server.processState != .running, return .unknown
// 2. If no health_check defined in manifest, return .unknown
// 3. Call the MCP tool specified in health_check
// 4. If tool succeeds within timeout, return .healthy
// 5. If tool fails or times out, return .unhealthy

func stopPeriodicChecks()
// Cancel background timer
```

**Health check manifest structure:**
```json
{
  "health_check": {
    "tool": "ping",            // MCP tool name to invoke
    "timeout": 5               // seconds (optional, default 10)
  }
}
```

**Key decisions:**
- Health checks run out-of-band, don't affect process state
- A server can be running but unhealthy (e.g., resource exhaustion)
- Health checks invoke MCP tool calls, not HTTP or TCP checks — consistent with MCP abstraction
- Timeout prevents hung checks from blocking subsequent checks

### 2.6 DependencyChecker

**Purpose:** Validate that runtime dependencies are satisfied before starting a server.

**Responsibilities:**
- Parse `dependencies` array from manifest
- For each dependency, check that required binary/version is available
- Return success or detailed error with missing/wrong version
- Called synchronously before ProcessManager.start()

**Dependency manifest structure:**
```json
{
  "dependencies": [
    {
      "name": "python",
      "binary": "python3",
      "version_check": "--version",
      "version_pattern": "Python (\\d+\\.\\d+\\.\\d+)",
      "required_version": "3.10.0"
    }
  ]
}
```

**Key methods:**
```
func checkDependencies(manifest: MCPManifest) async throws -> DependencyCheckResult
// For each dependency:
//   1. Check if binary exists in PATH
//   2. If version_check specified, run binary + args, parse output with regex
//   3. Compare against required_version (semantic versioning)
//   4. Collect errors if any fail
// Return .pass or .fail(reasons: [String])

struct DependencyCheckResult {
    let passed: Bool
    let details: [DependencyCheckDetail]
}

struct DependencyCheckDetail {
    let name: String
    let status: String               // "pass", "not_found", "version_mismatch"
    let found: String?               // actual version or binary path
    let required: String?
}
```

**Key decisions:**
- Version checking is optional — manifests without versions always pass (if binary exists)
- Version patterns use regex; manifest author provides pattern and semantic version matcher
- Dependency checks run at start time, not at discovery — avoids scanning delays
- Errors from dependency check are surfaced as startup failure, not silent skip

### 2.7 KeychainManager

**Purpose:** Securely store and retrieve server secrets from macOS Keychain.

**Responsibilities:**
- Store credentials with service identifier `com.inwestomat.shipyard`
- Retrieve credentials by key name
- Sanitize and inject secrets into process environment variables
- Never log or display secrets (except count and key names)

**Key methods:**
```
func storeSecret(key: String, value: String) throws
// Store value in Keychain with service "com.inwestomat.shipyard", account=key

func retrieveSecret(key: String) throws -> String
// Retrieve value from Keychain, throw if not found

func injectSecrets(from keys: [String]) async throws -> [String: String]
// For each key in manifest.env_secret_keys:
//   1. Retrieve value from Keychain
//   2. Collect as [key: value]
// Return dictionary suitable for NSProcess.environment merge
// If any key is missing, throw error (fail-fast)
```

**Key decisions:**
- Single service identifier for all servers (simpler UX, easier secret management)
- Missing secret causes startup failure (explicit, not silent)
- No secret values in logs — only "[REDACTED]" or key counts
- Keychain access is synchronous (fast and simple)

### 2.8 LogBuffer

**Purpose:** Circular buffer for recent server logs from multiple channels.

**Responsibilities:**
- Maintain three separate circular buffers: stdout, stderr, structured
- Append lines with timestamp and channel label
- Bound memory usage (configurable max lines, default 1000 per channel)
- Provide read access for UI display and export

**Key methods:**
```
func append(channel: LogChannel, line: String, timestamp: Date = .now)
// Add line to the appropriate circular buffer, discard oldest if full

func all() -> [LogEntry]
// Return all entries, interleaved by timestamp, most recent last

func clear()
// Clear all buffers

struct LogEntry {
    let timestamp: Date
    let channel: LogChannel           // stdout, stderr, structured
    let text: String
}

enum LogChannel {
    case stdout, stderr, structured
}
```

**Key decisions:**
- Separate channels allow filtering in UI (show only errors, for example)
- Timestamp for every line (aids debugging async issues)
- Circular buffer prevents unbounded memory growth — servers can run for hours
- Not a replacement for persistent logging — UI buffer is for recent context only

---

## 3. Integration Points

### 3.1 MCPBridge (child process gateway)

**Created by:** ProcessManager.start()
**Lifecycle:** One per running server; destroyed at ProcessManager.stop()
**Purpose:** Gateway between native UI and child MCP server process

**Interaction:**
- ProcessManager creates MCPBridge after successful NSProcess launch
- Bridge manages stdio communication with the child process
- Requests from UI route through gateway to child
- Responses from child are captured and forwarded to UI

**Key decision:** Bridge is NOT part of this spec — it's defined separately in ADR 0002 and implemented in `MCPBridge.swift`. This spec treats it as a black box: "ProcessManager creates one bridge per running server."

### 3.2 UI Components (MainWindow, MCPRowView)

**Consumer of:** MCPServer model, ProcessManager actions

**Responsibilities:**
- Display list of servers (from MCPRegistry)
- Show state indicators: green (running), red (error), gray (idle)
- Show resource stats: PID, CPU %, memory %
- Show health status: green (healthy), orange (unknown), red (unhealthy)
- Provide start/stop/restart buttons
- Display recent logs (from LogBuffer)
- Handle user actions (start, stop, restart)

**Key components:**
```
MainWindow (Servers tab, ⌘1)
├── MCPRegistryView (list of servers)
│   └── MCPRowView (per-server card)
│       ├── State indicator + name/version
│       ├── Start/Stop/Restart buttons
│       ├── Resource stats (PID, CPU, memory)
│       ├── Health status
│       └── Recent logs (scrollable)
```

**Key decision:** UI uses model bindings (@State, @ObservedObject) — no @Environment for observability objects (ADR 0005). ProcessManager and HealthChecker are injected as dependencies.

### 3.3 Logging (ADR 0004 — three-channel logging)

**Three channels:**
1. **Stdout** — normal process output
2. **Stderr** — error output from process
3. **Structured** — Shipyard's own structured logs (JSON, formatted)

**Implementation:**
- ProcessManager captures both pipes and routes to LogBuffer (channels: stdout/stderr)
- Structured logs come from Shipyard code: `logger.info("Server started", metadata: ["pid": pid])` → LogBuffer (channel: structured)
- All three channels appear in Console.app (subsystem: `com.inwestomat.shipyard.server`)

**Key decision:** Three channels are separate in LogBuffer, but all are logged to OSLog for persistent access. UI can filter by channel.

---

## 4. Workflows

### 4.1 App Startup

```
1. MCPRegistry.scan()
   - Walk _Tools/mcp/*/manifest.json
   - Parse each manifest
   - Build in-memory registry
   - Errors are logged, registry continues

2. HealthChecker.startPeriodicChecks()
   - Start background timer (30s interval)

3. UI renders MCPRegistryView
   - Servers shown in idle state
   - No processes running yet
```

**Duration:** <500ms (registry scan is fast, no process launches)

### 4.2 User starts a server

```
1. UI: User clicks Start button on MCPRowView
2. UI → ProcessManager.start(server)

   a. DependencyChecker.checkDependencies()
      - Validate Python version, etc.
      - If fail, update server.lastError, return error
      - UI shows error toast

   b. KeychainManager.injectSecrets()
      - Retrieve secrets from Keychain
      - Merge with manifest.env
      - If fail (secret not found), return error

   c. NSProcess creation
      - Set working directory (manifest.workingDirectory)
      - Set environment (plain vars + secrets)
      - Set up pipes for stdout/stderr
      - Launch process

   d. ProcessManager.captureStdout() [async background task]
      - Start reading from stdout pipe
      - Forward lines to server.logBuffer
      - Log to OSLog

   e. ProcessManager.captureStderr() [async background task]
      - Start reading from stderr pipe
      - Forward lines to server.logBuffer (marked as stderr)
      - Log to OSLog with error severity

   f. Create MCPBridge
      - Pass process stdin/stdout to bridge
      - Bridge ready to handle MCP requests

   g. ProcessManager.monitorResources() [async background task]
      - Poll process CPU/memory every 2s
      - Update server.resourceStats

   h. Update server.processState = .running

3. UI reactively updates (green indicator, PID visible, logs flowing)
```

**Typical duration:** 2–3 seconds (process launch + pipe setup)

**Error cases:**
- Dependency check fails → server.processState = .error, show reason in UI
- Keychain secret missing → server.processState = .error, show reason in UI
- Process launch fails (no such binary) → server.processState = .error, OS error shown
- Pipe creation fails (rare) → .error state

### 4.3 HealthChecker runs a periodic check

```
Every 30 seconds (while app is running):

1. HealthChecker.startPeriodicChecks() timer fires

2. For each server in MCPRegistry:
   a. If server.processState != .running, skip
   b. If manifest.health_check not defined, skip
   c. Call HealthChecker.checkHealth(server) async

      - Invoke the MCP tool specified in health_check.tool
      - Wait up to health_check.timeout (default 10s)
      - If tool returns success, healthStatus = .healthy
      - If tool errors or times out, healthStatus = .unhealthy

   d. Update server.lastHealthCheck = now()
   e. Log result with structured logging

3. UI reactively updates health indicators
```

**Parallelism:** All server health checks run in parallel (async tasks), not sequentially.

### 4.4 User stops a server

```
1. UI: User clicks Stop button
2. UI → ProcessManager.stop(server, timeout: 5)

   a. Send SIGTERM to process

   b. Wait up to 5 seconds for graceful shutdown
      - Poll process.isRunning in loop (0.1s intervals)
      - If process exits, go to step c

   c. If timeout exceeded:
      - Send SIGKILL
      - Process forcibly terminated

   d. Close stdout/stderr pipes
      - Cancel captureStdout/captureStderr tasks
      - Flush any remaining buffered output

   e. Destroy MCPBridge

   f. Clear server.resourceStats (no longer valid)

   g. Update server.processState = .idle

3. UI reactively updates (gray indicator, no PID, no resource stats)
```

**Typical duration:** <1 second (SIGTERM usually works)
**Worst case:** 5 seconds (timeout → SIGKILL)

### 4.5 User restarts a server

```
1. UI: User clicks Restart button
2. UI → ProcessManager.restart(server)

   a. ProcessManager.stop(server)
   b. Brief delay (100ms) to ensure cleanup
   c. ProcessManager.start(server)

3. Same transitions as 4.2 and 4.4 combined
```

**Typical duration:** 5–7 seconds (stop + start)

### 4.6 Registry refresh (new manifest added to disk)

```
1. User or script adds new manifest.json file to _Tools/mcp/*/
2. UI: User clicks "Refresh" button (or auto-refresh trigger)
3. MCPRegistry.scan() [async background task]

   a. Walk _Tools/mcp/*/manifest.json again
   b. Parse new/changed manifests
   c. Update internal registry
   d. Remove entries for manifests that no longer exist

4. UI reactively reflects new servers
```

**Key decision:** Registry refresh does NOT stop running servers — it only updates the list of available servers.

---

## 5. Error Handling

### 5.1 Startup errors (ProcessManager.start())

| Error | Root Cause | User Sees | Action |
|-------|-----------|-----------|--------|
| Dependency check fails | Binary not in PATH, or version mismatch | Error toast + details in logs | User installs missing tool or corrects manifest |
| Secret not in Keychain | env_secret_keys references non-existent key | Error toast + "missing key: X" | User stores secret in Keychain app |
| Binary not found | manifest.command doesn't exist | OS error in logs | User corrects manifest.command or PATH |
| Permission denied | Executable bit not set, or user lacks permission | OS error in logs | User fixes file permissions |
| Pipe creation fails | Very rare, system resource exhaustion | .error state, "cannot create pipes" | Restart app or free resources |

**Handling:** All startup errors land in `server.lastError` and `server.processState = .error`. UI displays error reason and suggests remediation.

### 5.2 Runtime errors (captureStdout/stderr)

| Error | Root Cause | User Sees | Action |
|-------|-----------|-----------|--------|
| Process crashes | Segfault, unhandled exception, etc. | Process output in logs + OS core dump info | Check logs, report bug |
| Pipe breaks | Process closes stdout/stderr unexpectedly | Last output logged, process .running state updates to .error | Check logs for crash reason |
| Resource exhaustion | Memory/CPU usage grows uncontrolled | monitorResources continues, UI shows high %, health check may timeout | User stops process, investigates manifest/command |

**Handling:** Log all output, update health status, let UI show context. No automatic recovery (don't auto-restart unless explicitly configured — future work).

### 5.3 Health check errors (HealthChecker.checkHealth())

| Error | Root Cause | User Sees | Action |
|-------|-----------|-----------|--------|
| Health check tool times out | MCP server not responding | healthStatus = .unhealthy | User investigates logs, may restart |
| Health check tool returns error | Server business logic failure | healthStatus = .unhealthy | User checks server logs for details |
| MCP bridge communication fails | Gateway issue | Health check fails gracefully, logged | Restart app or process |

**Handling:** Health check failures don't affect process state — only healthStatus. UI shows orange/red indicator. User can investigate logs and decide to stop/restart.

---

## 6. Test Coverage

**Scope:** ~109 tests across Sessions 26–53 (Sessions number indicates implementation maturity)

**Categories:**

| Category | Tests | Key scenarios |
|----------|-------|---------------|
| MCPRegistry | ~15 | Manifest discovery, parsing, invalid manifests, refresh |
| ProcessManager | ~35 | Start, stop, restart, timeout handling, pipe capture, resource monitoring |
| HealthChecker | ~20 | Health check invocation, timeouts, parallel checks, state updates |
| DependencyChecker | ~15 | Dependency validation, version parsing, missing binaries, pass/fail |
| KeychainManager | ~12 | Store, retrieve, inject, missing secret error |
| LogBuffer | ~8 | Append, circular overflow, interleaving, clear |
| Integration | ~4 | Full startup flow, full stop flow, restart flow |

**Testing discipline (per RTK rules):**
- No tests are skipped or disabled
- Failing tests are treated as spec signals — if test fails, spec or implementation must change
- All error cases have explicit tests — no "if error, return nil"

---

## 7. Configuration and Defaults

### 7.1 Scan directory

**Default:** `_Tools/mcp/*/manifest.json`
**Configurable in:** `Shipyard.xcconfig` or runtime (not yet UI)

### 7.2 Health check interval

**Default:** 30 seconds
**Configurable in:** App preferences (future work)

### 7.3 Process stop timeout

**Default:** 5 seconds
**Configurable in:** App preferences (future work)

### 7.4 Log buffer size

**Default:** 1000 lines per channel
**Configurable in:** App preferences (future work)

### 7.5 Keychain service identifier

**Fixed:** `com.inwestomat.shipyard`
**Rationale:** Single service for all servers simplifies secret management

---

## 8. Security Considerations

### 8.1 Secret handling

**Requirement:** Secrets (API keys, tokens) must never appear in logs or UI.

**Implementation:**
- Stored exclusively in macOS Keychain
- Retrieved only at process launch time
- Merged into NSProcess environment (in-memory, never persisted)
- LogBuffer logs only "[REDACTED]" when environment variables are logged
- Manifest.json files are not encrypted (assume read permissions are correct)

**Audit trail:** OSLog records "injected N secrets" but not the values.

### 8.2 Manifest loading

**Assumption:** Manifest files are trusted (in git repo, no untrusted input)

**No validation of:**
- Binary path traversal (e.g., `../../../etc/passwd`) — assumed trusted
- Shell metacharacters (e.g., `; rm -rf /`) — args are passed to execve, no shell

**Validated:**
- JSON schema (required fields present)
- Dependency version patterns (regex compiled safely)

### 8.3 Process isolation

**Assumption:** Child MCP processes run with same user as Shipyard app

**Child process inherits:**
- User ID (sandboxed app runs as loggedInUser)
- Home directory
- PATH
- Keychain access (via service `com.inwestomat.shipyard`)

**Child process does NOT inherit:**
- File access sandboxes (if Shipyard is sandboxed)
- Code signing restrictions

**Future work:** Separate Keychain service per server for finer-grained access control

### 8.4 Pipe handling

**Risk:** Pipe buffer overflow if child process writes faster than Shipyard reads

**Mitigation:**
- Pipes configured with default OS buffers (typically 64KB)
- captureStdout/stderr run in background, don't block process management
- If pipe fills up, write blocks child process (backpressure — acceptable)

---

## 9. Manifest JSON Schema

**Example manifest.json:**

```json
{
  "name": "mac-runner",
  "version": "1.0.0",
  "description": "Local command execution MCP server",
  "command": "python3",
  "args": ["-m", "mcp_server_mac_runner"],
  "env": {
    "LOG_LEVEL": "INFO"
  },
  "env_secret_keys": ["OPENAI_API_KEY"],
  "dependencies": [
    {
      "name": "python",
      "binary": "python3",
      "version_check": "--version",
      "version_pattern": "Python (\\d+\\.\\d+\\.\\d+)",
      "required_version": "3.10.0"
    }
  ],
  "health_check": {
    "tool": "ping",
    "timeout": 5
  },
  "logging": {
    "level": "info",
    "format": "json"
  },
  "install": {
    "description": "Requires Python 3.10+",
    "script": "pip install mcp-server-mac-runner"
  }
}
```

**Field descriptions:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| name | string | yes | Server name, used in UI and logs |
| version | string | yes | Semantic version (any format, not parsed) |
| description | string | no | Short description for tooltips |
| command | string | yes | Binary name (e.g., "python3"), resolved via PATH |
| args | string[] | yes | Command-line arguments (not shell-parsed) |
| env | object | no | Plain environment variables |
| env_secret_keys | string[] | no | Keys to inject from Keychain |
| dependencies | object[] | no | Runtime requirements |
| health_check | object | no | Health check tool and timeout |
| logging | object | no | Log level and format (informational) |
| install | object | no | Installation instructions (informational) |

---

## 10. ADR References

### ADR 0001 — Native Swift Implementation
Shipyard is implemented in Swift and SwiftUI, not Python or Electron. Rationale: native macOS integration (Keychain, process management, UI responsiveness).

### ADR 0002 — MCPBridge Pattern
One MCPBridge instance per running server, created at process start, destroyed at stop. Bridges the native UI to child process stdio.

### ADR 0004 — Mandatory Three-Channel Logging
Stdout, stderr, and structured logs are separate channels. All three logged to OSLog; UI filters as needed.

### ADR 0005 — No @Environment in Commands
Observability objects (ProcessManager, HealthChecker) are NOT injected via @Environment. Instead, they are explicit constructor/method parameters. This improves testability (no implicit SwiftUI state).

---

## 11. Future Work

### 11.1 Process restart policies (not yet implemented)

Manifest could specify:
```json
{
  "restart_policy": {
    "on_crash": "auto",           // auto, manual, never
    "max_retries": 3,
    "retry_delay_seconds": 5
  }
}
```

### 11.2 Resource limits (not yet implemented)

Manifest could specify:
```json
{
  "resource_limits": {
    "max_cpu_percent": 80,
    "max_memory_mb": 1024,
    "kill_on_exceed": false        // log warning, don't kill
  }
}
```

### 11.3 Pre/post hooks (not yet implemented)

Manifest could specify:
```json
{
  "hooks": {
    "pre_start": "setup.sh",       // shell script to run before starting
    "post_start": "health_seed.py", // warm up caches
    "pre_stop": "cleanup.sh"        // graceful shutdown tasks
  }
}
```

### 11.4 Separate Keychain service per server (future)

Instead of single `com.inwestomat.shipyard` service, allow:
```json
{
  "keychain_service": "com.inwestomat.shipyard.mac-runner"
}
```

---

## 12. Completeness Checklist

- [x] MCPRegistry — discovery and maintenance
- [x] MCPManifest model — static configuration
- [x] MCPServer model — runtime state
- [x] ProcessManager — lifecycle control
- [x] HealthChecker — periodic health validation
- [x] DependencyChecker — pre-flight checks
- [x] KeychainManager — secret storage and injection
- [x] LogBuffer — three-channel logging
- [x] UI integration (MainWindow, MCPRowView)
- [x] Error handling across all components
- [x] ~109 tests (Sessions 26–53)

---

## 13. Session and Build History

| Session | Milestone |
|---------|-----------|
| 26–28 | Core models (MCPManifest, MCPServer, ProcessManager) |
| 29–30 | Dependency checking, Keychain integration |
| 31–35 | Health checking, resource monitoring |
| 36–40 | LogBuffer, three-channel logging |
| 41–45 | UI integration (MainWindow, MCPRowView) |
| 46–50 | Error handling, edge cases |
| 51–53 | Final testing, documentation |

**Final test count:** ~109 tests (unit + integration)

---

## Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-03-16 | 1.0 | Initial specification — complete feature implemented and tested |
