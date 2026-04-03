---
id: SPEC-003
priority: 1
layer: 1
type: feature
status: done
after: [SPEC-001]
prior_attempts: []
created: 2026-03-16
---

# Logging & Observability

## Problem

Shipyard operators need comprehensive visibility into all system operations — both the ShipyardBridge proxy and the Shipyard.app itself, plus lifecycle events from child MCP servers. Without structured logging, diagnosing failures, tracing tool calls, and understanding system state requires reading scattered logs or running in the debugger. This slows incident response and makes post-mortem analysis difficult.

**Why now:** Shipyard is growing to support many child MCPs. Without unified observability, debugging multi-server interactions becomes exponentially harder. ADR 0004 mandates three-channel logging as a core invariant.

## Requirements

- [x] Implement three-channel logging (file, stderr, socket) that writes simultaneously to all channels
- [x] BridgeLogger for ShipyardBridge with JSONL file output (`~/.shipyard/logs/bridge.jsonl`)
- [x] AppLogger for Shipyard.app with JSONL file output (`~/.shipyard/logs/app.jsonl`)
- [x] LogStore: in-memory circular buffer (5,000 entries) fed from AppLogger and socket forwarding
- [x] LogFileWriter for persistent per-server stderr capture (`~/.shipyard/logs/{server-name}/stderr-*.log`)
- [x] Automatic file rotation at 10 MB (bridge/app) and 5 MB (per-server stderr)
- [x] Socket method `log_event` for bridge→app log forwarding (best-effort, info+ level only)
- [x] Socket method `logs` for external log retrieval with filtering
- [x] LogFilter for querying by source, level, category, text, and date range
- [x] SystemLogView: ⌘3 System Logs tab with filtering, search, and export
- [x] Export logs in JSONL, CSV, and Text formats via ⌘E keyboard shortcut
- [x] MCPNotificationParser to extract log-like information from MCP protocol notifications
- [x] Three-channel atomicity: all three channels succeed or fail together (transactional guarantee)
- [x] Graceful degradation when socket unavailable, file write fails, or rotation fails

## Acceptance Criteria

- [x] AC 1: BridgeLogger writes entries to JSONL file, stderr, and socket simultaneously
- [x] AC 2: AppLogger writes entries to JSONL file, stderr, and LogStore simultaneously
- [x] AC 3: LogStore maintains 5,000 entries with FIFO eviction; filtering returns correct subset
- [x] AC 4: JSONL file rotation triggers at 10 MB threshold; retains 5 recent files (50 MB total)
- [x] AC 5: Per-server stderr rotation triggers at 5 MB; retains 10 files per server (50 MB per server)
- [x] AC 6: System Logs tab displays live stream with filter buttons (source, level, category)
- [x] AC 7: Search box filters logs by substring match in message field
- [x] AC 8: Export (⌘E) saves filtered entries in JSONL, CSV, or Text format
- [x] AC 9: `log_event` socket method forwards info+ level entries from bridge to app in <100ms
- [x] AC 10: `logs` socket method retrieves recent entries with mcp_name, level, and line count filtering
- [x] AC 11: Per-server stderr files capture raw child MCP output without JSON encoding
- [x] AC 12: MCPNotificationParser extracts tools/list_changed, resources/list_changed, prompts/list_changed
- [x] AC 13: Logging overhead ≤1 ms per entry (all three channels combined)
- [x] AC 14: System Logs tab remains responsive (60 FPS) with 5,000 entries displayed
- [x] AC 15: LogStore memory usage ≤10 MB for 5,000 entries
- [x] AC 16: JSONL file rotation is non-blocking (background thread)
- [x] AC 17: Socket forwarding gracefully degrades if app is unavailable (no error propagation)
- [x] AC 18: JSONL files are never truncated; new entries always appended
- [x] AC 19: Log files created with 0600 permissions (user-readable only)
- [x] AC 20: fsync on critical entries (error, lifecycle) to prevent data loss on crash

## Context

**Key Files:**
- Bridge logger: `ShipyardBridgeLib/BridgeLogger.swift`
- App logger: `Shipyard/Services/AppLogger.swift`
- In-memory store: `Shipyard/Services/LogStore.swift`
- JSONL persistence: `Shipyard/Services/LogFileWriter.swift`
- Entry schema: `Shipyard/Models/BridgeLogEntry.swift`
- UI display: `Shipyard/Views/SystemLogView.swift`, `Shipyard/Views/LogViewer.swift`
- Tests: `ShipyardBridgeTests/BridgeLogger*.swift`, `ShipyardTests/AppLogger*.swift`, `ShipyardTests/LogStore*.swift`

**Architecture:**
- All logging routes through a single struct `BridgeLogEntry` (timestamp, level, category, source, message, metadata)
- Bridge-side logging: file + stderr + socket (fire-and-forget, 100 ms timeout)
- App-side logging: file + stderr + LogStore (direct append, no socket)
- LogStore: FIFO circular buffer, 5,000 capacity, thread-safe with async/await
- Rotation: background DispatchQueue, never blocks logging thread

**Key Invariant (ADR 0004):**
All logging must write to three channels simultaneously. No channel may be disabled. Logging is mandatory and non-optional.

**Socket Protocol:**
- `log_event`: Bridge→App log forwarding (info+ only, best-effort)
- `logs`: External client log retrieval with filtering (mcp_name, level, line count)

## Alternatives Considered

1. **Two-channel logging (file + stderr):** Rejected because app-side logs wouldn't reach file during app startup or crashes. Three channels guarantee visibility in all running states.

2. **Async-only logging:** Rejected because critical entries (errors, lifecycle) must fsync immediately. Hybrid sync (critical) + async (info/debug) provides safety without overhead.

3. **Centralized log aggregation service:** Rejected (out of scope, future enhancement). Current design supports optional remote forwarding via external client socket calls.

4. **Per-entry socket ACK:** Rejected because ACKs add latency and complexity. Best-effort delivery with graceful degradation is sufficient.

## Scenarios

1. **Live debugging:** Developer opens System Logs tab (⌘3) → filters by source="bridge" + level="warning" → watches tool call warnings stream in real-time → pauses stream to inspect metadata tree → exports last 100 entries to file for offline analysis.

2. **Post-crash recovery:** App crashes mid-operation → developer restarts Shipyard → opens System Logs → scans app.jsonl file (restored from disk) → traces events leading up to crash by filtering category="lifecycle" → confirms three-channel logging prevented data loss.

3. **Multi-server debugging:** Child MCP "lmstudio" becomes unresponsive → developer filters SystemLogView by source="lmstudio" → sees last 10 stderr entries from `~/.shipyard/logs/lmstudio/stderr-1.log` → notices raw error message indicating file descriptor exhaustion → identifies leak.

4. **Rotation and retention:** Shipyard runs for 48 hours with debug logging → bridge.jsonl grows to 10 MB → rotation triggers automatically → new bridge.jsonl created, old file renamed to bridge.1.jsonl → process continues seamlessly. After 5 rotations, bridge.5.jsonl is deleted to stay within 50 MB budget.

5. **Graceful degradation:** App is not running → BridgeLogger attempts socket forwarding → timeout fires after 100 ms → socket error is silently logged to stderr + file only → bridge continues processing without blocking.

## Exemplar

- **Source:** Project ADR 0004 (Mandatory Three-Channel Logging) defines the invariant and rationale
- **What to learn:** Why transactional guarantees (all-or-nothing per entry) matter; why best-effort with graceful degradation is sufficient for non-critical channels
- **What NOT to copy:** Over-engineered remote aggregation; per-client filtering (all clients see same stream)

## Out of Scope

- Real-time remote log aggregation or cloud streaming (future)
- Persistent cross-machine log search (future)
- Integration with external services (Datadog, Splunk, etc.)
- Per-socket-client log filtering (all clients receive same stream)
- Log compression or archival beyond file rotation
- Advanced sampling or rate-limiting (future polish)
- Custom log levels defined by MCPs (future)
- Alerting on error thresholds (future)

---

## Notes for the Agent

**Entry Schema (BridgeLogEntry):**
```json
{
  "timestamp": "2026-03-13T14:52:30.123Z",  // ISO 8601 UTC
  "level": "info",                          // debug, info, warning, error
  "category": "mcp",                        // mcp, socket, gateway, health, lifecycle
  "source": "bridge",                       // "bridge", "app", or MCP name
  "message": "Child MCP 'mac-runner' started (PID 18472)",
  "metadata": {
    "mcp_name": "mac-runner",
    "pid": 18472,
    "version": "1.0"
  }
}
```

**Three-Channel Write Pattern:**
1. Serialize entry to JSONL, then to single-line stderr text
2. Write to file (synchronous, fsync on critical)
3. Write to stderr (always, non-blocking)
4. Async task: attempt socket forwarding with 100 ms timeout (fire-and-forget)

**Rotation Logic:**
- Check file size before every append
- If ≥ 10 MB (bridge/app) or ≥ 5 MB (per-server): rename current → numbered file, create new
- Delete oldest file if retention limit exceeded (5 for bridge/app, 10 per server)
- Run in background DispatchQueue to avoid blocking logger thread

**File Permissions:**
All log files created with mode 0600 (user read/write only). No world-readable permissions.

**Socket Timeouts:**
- `log_event`: 100 ms timeout; connection failure is non-fatal
- `logs`: External client call; standard timeout handling

**LogFilter Example:**
```swift
let filter = LogFilter(
  sources: ["bridge", "mac-runner"],
  levels: [.warning, .error],
  since: Date().addingTimeInterval(-3600)  // last hour
)
let filtered = logStore.entries(filter: filter)
```

**Export Formats:**
- JSONL: one entry per line, identical to stored format
- CSV: flattened columns (timestamp, level, source, category, message, metadata-as-JSON)
- Text: plain text, one entry per line, suitable for chat/email

**Testing:**
See `ShipyardTests/` for unit tests of LogStore filtering, BridgeLogger three-channel writes, and LogFileWriter rotation. Integration tests verify atomicity and graceful degradation. Manual tests verify 1+ hours of continuous operation without data loss.

**Performance Targets:**
- Logging adds ≤1 ms per entry
- LogStore filters in ≤200 ms
- System Logs tab at 60 FPS with 5,000 entries
- Socket forwarding ≤50 ms (info+ level)
- File rotation non-blocking

**Crash Safety:**
JSONL files are fsync'd on error/lifecycle entries, ensuring post-crash recovery. App can restore its entire log history from app.jsonl on restart.
