# Spec 003: Logging & Observability

**Status**: Accepted (fully implemented)
**Version**: 1.0
**Last Updated**: 2026-03-16 (Session 56)
**Author**: AI assistant
**Deciders**: project maintainer, AI assistant
**Related ADR**: [ADR 0004 — Mandatory Three-Channel Logging](../adr/0004-mandatory-three-channel-logging.md)

---

## Overview

Shipyard's Logging & Observability feature provides comprehensive visibility into all system operations: both the ShipyardBridge proxy and the Shipyard.app itself, plus structured capture of child MCP server lifecycle events. All logging is mandatory, structured (JSONL), and routed through three independent channels simultaneously (file, stderr, socket). The feature enables real-time log streaming in the app UI, persistent historical access, and comprehensive post-mortem analysis.

**Key Invariant (ADR 0004)**: All logging must write to three channels simultaneously. No channel may be disabled or removed. Logging is never optional — it's a core value.

---

## Goals

1. **Guaranteed Visibility**: Every log entry reaches at least one consumer, in every running state (app open, closed, or crashed).
2. **Real-Time Observability**: Users and developers can watch live log streams in the System Logs tab (⌘3).
3. **Historical Analysis**: Persistent JSONL files enable post-mortem investigation without running state dependency.
4. **Structured Logging**: All entries contain timestamp, level, category, source, and optional metadata — enabling filtering, aggregation, and analytics.
5. **Child Server Visibility**: MCP protocol notifications and stderr from child servers are captured and integrated into the unified log stream.
6. **Minimal Overhead**: Three-channel writes must not measurably impact performance.

---

## Non-Goals

- Real-time remote log aggregation or cloud streaming
- Persistent log search across multiple machines
- Integration with external logging services (Datadog, Splunk, etc.)
- Per-socket-client log filtering (all clients see the same stream)
- Compression or archival beyond file rotation

---

## Functional Requirements

### 1. Bridge-Side Logging (ShipyardBridge)

#### 1.1 BridgeLogger Component

**Purpose**: Handles all structured logging on the bridge side, routing entries to three channels.

**Three Mandatory Channels**:

1. **JSONL File** (`~/.shipyard/logs/bridge.jsonl`)
   - Location: `~/.shipyard/logs/bridge.jsonl`
   - Format: newline-delimited JSON
   - Rotation: At 10 MB per file; retains 5 recent files (50 MB total)
   - Persistence: Survives across bridge restarts
   - Structured schema: See §3.2 (BridgeLogEntry)

2. **stderr** (standard error stream)
   - Destination: Process stderr (inherited by parent: Claude Desktop)
   - Visibility: Captured by Shipyard.app (if running) and displayed in System Logs tab
   - Fallback: When app is not running, Claude Desktop still receives stderr (audit trail)
   - Format: Single-line text (derived from JSONL entry)
   - Level threshold: All levels (debug+)

3. **Socket Forwarding** (real-time to Shipyard.app)
   - Method: `log_event` socket call (§4.1)
   - Level threshold: info+ (debug excluded to reduce noise)
   - Delivery: Fire-and-forget, best-effort (no acknowledgment)
   - Target: Shipyard.app's LogStore (§2.1)
   - Timeout: 100 ms (connection failure is non-fatal)

#### 1.2 Log Entry Schema (BridgeLogEntry)

```json
{
  "timestamp": "2026-03-13T14:52:30.123Z",
  "level": "info",
  "category": "mcp",
  "source": "bridge",
  "message": "Child MCP 'mac-runner' started (PID 18472)",
  "metadata": {
    "mcp_name": "mac-runner",
    "pid": 18472,
    "version": "1.0"
  }
}
```

**Fields**:
- `timestamp` (ISO 8601 UTC): Entry creation time
- `level` (string): `debug`, `info`, `warning`, `error`
- `category` (string): `mcp`, `socket`, `gateway`, `health`, `lifecycle`
- `source` (string): Always `"bridge"` on bridge side
- `message` (string): Human-readable summary
- `metadata` (object, optional): Additional context (mcp_name, pid, tool_name, etc.)

#### 1.3 Structured Logging API (BridgeLogger)

```swift
class BridgeLogger {
  // Convenience methods (each writes to all three channels)
  func debug(_ msg: String, category: String, metadata: [String: Codable]? = nil)
  func info(_ msg: String, category: String, metadata: [String: Codable]? = nil)
  func warning(_ msg: String, category: String, metadata: [String: Codable]? = nil)
  func error(_ msg: String, category: String, metadata: [String: Codable]? = nil)

  // Direct entry creation
  func log(_ entry: BridgeLogEntry)
}
```

**Usage Example**:
```swift
logger.info(
  "Tool call completed",
  category: "gateway",
  metadata: [
    "tool": "mac-runner__run_command",
    "duration_ms": 245
  ]
)
```

---

### 2. App-Side Logging (Shipyard.app)

#### 2.1 AppLogger Component

**Purpose**: Structured logging from Shipyard.app's SwiftUI components and services.

**Three Mandatory Channels**:

1. **JSONL File** (`~/.shipyard/logs/app.jsonl`)
   - Location: `~/.shipyard/logs/app.jsonl`
   - Rotation: At 10 MB per file; retains 5 recent files
   - Format: Identical to bridge entries (§3.2)
   - Persistence: Available for post-crash analysis

2. **stderr** (app process stderr)
   - Destination: macOS process stderr (visible via Xcode console during development)
   - Usage: Development/debugging only

3. **Socket Delivery** (to LogStore)
   - Internal: AppLogger writes directly to LogStore; no socket call needed
   - Real-time: Entries appear in LogStore immediately

#### 2.2 LogStore Component

**Purpose**: In-memory circular buffer of recent log entries, fed from both app-local and socket-forwarded sources.

**Specification**:
- **Capacity**: 5,000 entries (approximate, ~5 MB memory footprint)
- **Eviction**: FIFO (oldest entries dropped when capacity exceeded)
- **Sources**:
  - AppLogger (all levels)
  - Socket forwarding from ShipyardBridge (`log_event` method)
  - MCPNotificationParser (extracted from MCP protocol notifications)
- **Thread Safety**: Async/await, suitable for SwiftUI @Observable
- **API**:
  ```swift
  class LogStore {
    func append(_ entry: BridgeLogEntry)
    func entries() -> [BridgeLogEntry]
    func entries(filter: LogFilter) -> [BridgeLogEntry]
    func clearAll()
  }
  ```

#### 2.3 LogFilter

**Purpose**: Efficient filtering of LogStore entries for UI display.

```swift
struct LogFilter {
  var sources: Set<String>?        // "bridge", "app", "{mcp-name}"
  var levels: Set<LogLevel>?       // debug, info, warning, error
  var categories: Set<String>?     // mcp, socket, gateway, health, lifecycle
  var text: String?                // substring match in message
  var since: Date?                 // entries after this timestamp
}
```

**Example**:
```swift
let filter = LogFilter(
  sources: ["bridge", "mac-runner"],
  levels: [.warning, .error],
  since: Date().addingTimeInterval(-3600)  // last hour
)
let filtered = logStore.entries(filter: filter)
```

#### 2.4 LogFileWriter Component

**Purpose**: Persistent per-server stderr capture to rotating log files.

**Specification**:
- **Location**: `~/.shipyard/logs/{server-name}/stderr-*.log`
  - One directory per child MCP
  - Rotation: At 5 MB per file; retains 10 recent files (50 MB per server)
- **Content**: Raw stderr output from child MCP processes (not JSON, plain text)
- **Use Case**: Diagnostic troubleshooting when child MCP produces unstructured output
- **Lifecycle**:
  - Created on first server start
  - Appended to on each subsequent start
  - Auto-rotated when file size exceeds threshold

---

### 3. User Interface (SystemLogView & LogViewer)

#### 3.1 System Logs Tab

**Keyboard Shortcut**: ⌘3 (System Logs tab)

**Components**:
- **Header**: Log level selector (All / Info+ / Warning+ / Error)
- **Source filter buttons**: "Bridge", "App", individual MCP names (dynamic, based on running servers)
- **Category filter buttons** (optional): "MCP", "Socket", "Gateway", "Health", "Lifecycle"
- **Search box**: Substring search in message field
- **Time range slider** (optional): Last 1 hour / 24 hours / all
- **Live toggle**: ON = stream new entries, OFF = show static snapshot
- **Export button** (⌘E): Save filtered entries to file
- **Reveal in Finder** (⌘⇧L): Open `~/.shipyard/logs/` directory

#### 3.2 Log Entry Display (SystemLogView)

Each entry displays:
- **Timestamp**: HH:MM:SS.mmm format (local time with timezone offset option)
- **Level badge**: Colored pill (🔵 debug, 🟦 info, 🟨 warning, 🟥 error)
- **Source label**: "bridge" / "app" / "{mcp-name}"
- **Category label**: "mcp", "socket", "gateway", "health", "lifecycle"
- **Message**: Full text (truncate to 200 chars in list, full text on select)
- **Metadata**: Expandable tree (show on click or hover)
- **Timestamp tooltip**: Full ISO 8601 + human-readable relative time

#### 3.3 Export Dialog

**Triggered by**: ⌘E (keyboard) or "Export Logs" button

**Format options**:
1. **JSONL** (default): One entry per line, identical to `~/.shipyard/logs/app.jsonl` format
2. **CSV**: Flattened columns (timestamp, level, source, category, message, metadata-as-JSON)
3. **Text**: Plain text, one entry per line, suitable for sharing in chat

**Dialog**:
- Preset: Last 100 / Last 1000 / All in buffer
- Custom range: Date/time pickers
- Filter applied: Apply current UI filters before export
- Filename: `shipyard-logs-{timestamp}.{ext}`
- Destination: Open save dialog, default to Documents/

---

### 4. Protocol: Socket & API

#### 4.1 Socket Method: `log_event` (Bridge → App)

**Purpose**: Fire-and-forget forwarding of log entries from bridge to app.

**Request**:
```json
{
  "method": "log_event",
  "params": {
    "timestamp": "2026-03-13T14:52:30.123Z",
    "level": "info",
    "category": "gateway",
    "source": "bridge",
    "message": "Gateway call completed",
    "metadata": { "tool": "mac-runner__run_command", "duration_ms": 245 }
  }
}
```

**Response**: None (fire-and-forget). On error, log is silently dropped (5s timeout).

**Semantics**:
- No acknowledgment expected
- If socket is unavailable, bridge continues normally (graceful degradation)
- Best-effort delivery; info+ level only (debug excluded to reduce spam)

#### 4.2 Socket Method: `logs` (External Client → App)

**Purpose**: Retrieve recent log lines for a specific server or aggregate view.

**Request**:
```json
{
  "method": "logs",
  "params": {
    "mcp_name": "mac-runner",
    "lines": 50,
    "level": "warning"
  }
}
```

**Response**:
```json
{
  "result": {
    "lines": [
      "{\"timestamp\": \"...\", \"level\": \"warning\", ...}",
      "..."
    ],
    "total_available": 1243
  }
}
```

**Parameters**:
- `mcp_name` (string, optional): Specific MCP filter. If omitted, return logs from app + bridge
- `lines` (integer, optional): Return N most recent entries (default: 100, max: 10,000)
- `level` (string, optional): Minimum level filter: "debug", "info", "warning", "error"

**Errors**:
- `invalid_mcp_name`: MCP name not found
- `invalid_level`: Unknown level string
- `buffer_empty`: No logs available

---

### 5. Child MCP Integration

#### 5.1 MCPNotificationParser

**Purpose**: Extract log-like information from MCP protocol notifications and feed to LogStore.

**Supported Notifications**:
- MCP 2.0 `resources/list_changed` → category: "mcp"
- MCP 2.0 `prompts/list_changed` → category: "mcp"
- MCP 2.0 `tools/list_changed` → category: "mcp"
- Custom notification types (future expansion)

**Behavior**:
```swift
class MCPNotificationParser {
  func parse(
    jsonrpcNotification: [String: Any],
    serverName: String
  ) -> BridgeLogEntry?
}
```

Example output:
```json
{
  "timestamp": "2026-03-13T14:52:30.456Z",
  "level": "info",
  "category": "mcp",
  "source": "mac-runner",
  "message": "Tools list changed (notification from child MCP)",
  "metadata": {
    "notification_type": "tools/list_changed",
    "server_name": "mac-runner"
  }
}
```

#### 5.2 Child Server stderr Capture

**Method**: ProcessManager attaches pipe to child MCP stderr at startup.

**Storage**: LogFileWriter (§2.4) writes to `~/.shipyard/logs/{server-name}/stderr-*.log`

**Display**: Optional "Child Logs" tab or expandable section in System Logs tab (filtered by source = server name).

---

## Non-Functional Requirements

### Performance

- **Logging Overhead**: ≤ 1 ms per entry (all three channels combined)
- **LogStore Memory**: ≤ 10 MB for 5,000 entries
- **Socket Forwarding Latency**: ≤ 50 ms (info+ level)
- **JSONL File Rotation**: Non-blocking; happens in background thread
- **UI Responsiveness**: Log list scrolling at 60 FPS with 5,000 entries; filtering ≤ 200 ms

### Reliability

- **Three-Channel Atomicity**: All three writes must complete or all must fail (transactional guarantee at entry level)
- **Graceful Degradation**:
  - If socket is unavailable: bridge logs to file + stderr only
  - If JSONL file write fails: log error to stderr + socket, continue
  - If file rotation fails: continue logging to current file (overwrite old entries if size exceeded)
- **No Data Loss**: JSONL files never truncated; new entries always appended
- **Crash Safety**: JSONL files are fsync'd on critical entries (error, lifecycle events)

### Security

- **File Permissions**: Log files created with 0600 (user-readable only)
- **Sensitive Data Redaction**: No API keys, tokens, or passwords in logs (caller's responsibility)
- **Access Control**: Logs only readable by the user who started Shipyard
- **No Network Export**: Logs never sent outside localhost (socket only)

### Observability

- **Structured Schema**: All entries conform to BridgeLogEntry schema (sortable, aggregatable, queryable)
- **Timestamps**: UTC ISO 8601, precise to milliseconds
- **Source Attribution**: Every entry tagged with source (bridge, app, or child MCP name)
- **Category Taxonomy**: Fixed set of categories for filtering and analytics

---

## Implementation Details

### Directory Structure

```
~/.shipyard/
├── logs/
│   ├── bridge.jsonl              # App-side: bridge logs
│   ├── app.jsonl                 # App-side: app logs
│   ├── mac-runner/
│   │   ├── stderr-1.log
│   │   ├── stderr-2.log
│   │   └── ...
│   ├── lmstudio/
│   │   └── stderr-1.log
│   └── ...
└── shipyard.sock
```

### Swift Type Definitions

**Core Types** (defined in `Logging/Types.swift`):

```swift
enum LogLevel: String, Codable {
  case debug = "debug"
  case info = "info"
  case warning = "warning"
  case error = "error"

  var isAtLeast(_ other: LogLevel) -> Bool {
    let order: [LogLevel] = [.debug, .info, .warning, .error]
    return order.firstIndex(of: self)! >= order.firstIndex(of: other)!
  }
}

struct BridgeLogEntry: Codable, Identifiable {
  var id: UUID = UUID()
  var timestamp: Date
  var level: LogLevel
  var category: String  // "mcp", "socket", "gateway", "health", "lifecycle"
  var source: String    // "bridge", "app", or mcp name
  var message: String
  var metadata: [String: AnyCodable]?
}

struct LogFilter {
  var sources: Set<String>?
  var levels: Set<LogLevel>?
  var categories: Set<String>?
  var text: String?
  var since: Date?
  var until: Date?

  func matches(_ entry: BridgeLogEntry) -> Bool {
    // Implement filtering logic
  }
}

@Observable
final class LogStore {
  private var entries: [BridgeLogEntry] = []
  private let capacity = 5000

  func append(_ entry: BridgeLogEntry) { }
  func entries() -> [BridgeLogEntry] { }
  func entries(filter: LogFilter) -> [BridgeLogEntry] { }
  func clearAll() { }
}

final class BridgeLogger {
  // Writes to: JSONL file + stderr + socket
  func log(_ entry: BridgeLogEntry) { }

  // Convenience methods
  func debug(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
  func info(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
  func warning(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
  func error(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
}

final class AppLogger {
  // Writes to: JSONL file + stderr + LogStore
  func log(_ entry: BridgeLogEntry) { }

  func debug(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
  func info(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
  func warning(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
  func error(_ msg: String, category: String, metadata: [String: Codable]? = nil) { }
}

final class LogFileWriter {
  func write(_ line: String, server: String? = nil) throws { }
  func rotate() throws { }
}

class MCPNotificationParser {
  func parse(notification: [String: Any], serverName: String) -> BridgeLogEntry? { }
}
```

### Three-Channel Write Implementation

Pseudocode for single entry logging:

```swift
private func log(_ entry: BridgeLogEntry) {
  let jsonLine = entry.toJSONL()
  let stderrLine = entry.toStderrLine()

  // Channel 1: JSONL file (synchronous, fsync on error/critical)
  do {
    try fileWriter.append(jsonLine)
  } catch {
    // Channel 2 fallback: ensure it reaches stderr
    fputs("LOGGING ERROR: \(error)\n", stderr)
  }

  // Channel 2: stderr (always non-blocking)
  fputs("\(stderrLine)\n", stderr)

  // Channel 3: socket forwarding (best-effort, 100 ms timeout)
  if entry.level.isAtLeast(.info) {
    Task {
      let timeout = try? await Task.sleep(nanoseconds: 100_000_000)  // 100 ms
      try? await socketForwarder.logEvent(entry)
    }
  }
}
```

### Rotation Logic

**JSONL File Rotation**:
1. Check file size before every append
2. If ≥ 10 MB:
   - Rename current file to `bridge.1.jsonl`, `bridge.2.jsonl`, etc.
   - Create new `bridge.jsonl`
   - Delete `bridge.5.jsonl` if it exists (retain only 5 files)
3. Non-blocking: run in background DispatchQueue

**Per-Server stderr Rotation**:
1. Similar logic, but rotated at 5 MB per file
2. Retain 10 files per server (50 MB total)
3. Format: `stderr-1.log`, `stderr-2.log`, …, `stderr-10.log`

---

## Integration Points

### ShipyardBridge Integration

**Bridge must call BridgeLogger for:**
- MCP startup/shutdown (category: lifecycle)
- Socket connection established/failed (category: socket)
- Gateway discovery updates (category: gateway)
- Tool call start/completion/error (category: gateway)
- Configuration reload (category: lifecycle)
- Timeout conditions (category: socket, gateway)

### Shipyard.app Integration

**App must call AppLogger for:**
- Child MCP start/stop/restart (category: lifecycle)
- Health check results (category: health)
- Configuration changes (category: lifecycle)
- UI state changes (optional, category: app)
- Export operations (category: app)

**App must feed LogStore from:**
- AppLogger (direct append)
- Socket `log_event` forwarding from bridge
- MCPNotificationParser output from child MCP notifications

---

## Acceptance Criteria

### Functional

- [ ] BridgeLogger writes all entries to JSONL file, stderr, and socket simultaneously
- [ ] AppLogger writes all entries to JSONL file, stderr, and LogStore simultaneously
- [ ] LogStore holds 5,000 entries with FIFO eviction; filtering works correctly
- [ ] JSONL file rotation occurs at 10 MB (bridge/app) and 5 MB (per-server stderr)
- [ ] System Logs tab displays live stream with filtering by source, level, category
- [ ] Export (⌘E) saves filtered entries in JSONL/CSV/Text format
- [ ] `logs` socket method retrieves recent entries with filtering
- [ ] `log_event` socket method forwards bridge logs to app in real-time
- [ ] Per-server stderr files capture child MCP output correctly
- [ ] MCPNotificationParser extracts events from MCP protocol notifications

### Non-Functional

- [ ] Logging adds ≤ 1 ms per entry (all three channels)
- [ ] System Logs tab remains responsive (60 FPS) with 5,000 entries
- [ ] LogStore memory usage ≤ 10 MB
- [ ] JSONL file rotation is non-blocking
- [ ] Socket forwarding gracefully degrades if app is unavailable
- [ ] JSONL files are never truncated; always append-only
- [ ] Log files are created with 0600 permissions (user-readable only)

### Coverage

- [ ] Unit tests: BridgeLogger, AppLogger, LogFileWriter, LogStore, LogFilter, MCPNotificationParser
- [ ] Integration tests: Three-channel write atomicity, rotation behavior, socket forwarding
- [ ] UI tests: System Logs tab filter/search, export, real-time stream
- [ ] Manual tests: 1 hour of continuous operation, export 10,000+ entries, verify file rotation

---

## Testing Strategy

### Unit Tests

**BridgeLogger**:
- Test three-channel write for each level/category combination
- Verify JSONL format correctness
- Test stderr formatting
- Mock socket forwarder; verify it's called with correct parameters
- Test level filtering (info+ excludes debug from socket)

**AppLogger**:
- Similar to BridgeLogger, but verify LogStore append instead of socket
- Test metadata encoding/decoding

**LogStore**:
- Test append, capacity limits, FIFO eviction
- Test filtering (by source, level, category, text, date range)
- Test thread safety with concurrent appends

**LogFilter**:
- Test each filter dimension independently
- Test combinations (e.g., source + level + text)

**LogFileWriter**:
- Test append, rotation trigger, file retention
- Test permission bits (0600)
- Test per-server directory creation

**MCPNotificationParser**:
- Test known notification types (tools/list_changed, etc.)
- Test unknown types (no crash, returns nil)
- Test metadata extraction

### Integration Tests

- **Three-Channel Atomicity**: All three channels succeed or all fail (no partial writes)
- **Rotation Behavior**: Verify file count, timestamp ordering, no data loss
- **Socket Forwarding**: Bridge logs appear in app's LogStore within 100 ms
- **Graceful Degradation**: App unavailable → bridge logs to file + stderr only

### Manual Testing

- Run Shipyard for 1+ hours, verify System Logs tab updates continuously
- Export 10,000+ entries, verify JSONL/CSV/Text formats
- Kill app mid-operation, verify bridge logs still written to file
- Trigger rotation (fill files beyond threshold), verify old entries accessible
- Monitor CPU/memory during high log volume (test with debug logging enabled)

---

## Future Considerations

### Possible Enhancements

1. **Real-time Log Search**: Full-text index for faster filtering across large buffers
2. **Log Aggregation**: Export across multiple Shipyard instances
3. **Custom Log Levels**: Allow MCPs to define custom severity levels
4. **Alerting**: Trigger notifications on error log thresholds
5. **Performance Metrics**: Capture & display p50/p95/p99 latencies per category
6. **Sampling**: Reduce debug log volume in high-throughput scenarios
7. **Remote Logging**: Optional syslog forwarding for integration environments

### Backwards Compatibility

- Log entry schema is versioned (current: 1.0)
- Future schema changes will add new optional fields
- Old parsing code will ignore unknown fields
- JSONL files are immutable; past entries never modified

---

## Related Documentation

- **ADR 0004**: [Mandatory Three-Channel Logging](../adr/0004-mandatory-three-channel-logging.md)
- **Architecture**: [Shipyard Architecture](../explanation/architecture.md)
- **Socket Protocol**: [Socket Protocol Reference](../reference/socket-protocol.md)
- **Keyboard Shortcuts**: [Keyboard Shortcuts Reference](../reference/keyboard-shortcuts.md)

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-16 | AI assistant | Initial Spec-Kit release. Accepted, fully implemented across Sessions 26-56. |

---

**Specification Owner**: AI assistant
**Implementation Status**: Accepted (Sessions 26–53)
**Last Implementation Update**: Session 56 (2026-03-16)
