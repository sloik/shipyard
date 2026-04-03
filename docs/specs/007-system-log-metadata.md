# Spec 007: System Log Metadata Enrichment

**Status:** Draft
**Author:** AI assistant
**Date:** 2026-03-26
**Version:** 1.0

---

## Problem Statement

The Shipyard logging infrastructure (Spec 003) defines a metadata field on every `BridgeLogEntry` and provides the UI machinery to display it. However, **100% of logging calls currently pass `nil` for metadata**, resulting in "(no metadata)" appearing when users expand log entries in the System Log tab (⌘3).

The metadata infrastructure is ready and unused. This spec defines:
1. **What metadata to capture** for every logging category (gateway operations, process lifecycle, discovery, socket I/O)
2. **When and where to add it** (audit of all call sites)
3. **Configurable argument logging** via a UI toggle (keys-only by default, full values opt-in)
4. **Backward compatibility** (old entries without metadata still display gracefully)

---

## Vision Statement

Users can **inspect the operational details of any log entry** without opening separate files or running diagnostics. Metadata answers "why did this take so long?" (duration_ms), "what arguments were passed?" (argument keys/values), "did the tool succeed?" (error codes), and "how much data was transferred?" (bytes in/out).

---

## Requirements

### Must Have (MVP)

#### 1. Gateway Call Metadata
Every `gateway_call` operation logged must include:
- `mcp_name` (string): Name of the target MCP (e.g., "mac-runner")
- `tool_name` (string): Full prefixed tool name (e.g., "mac-runner__run_command")
- `original_tool_name` (string): Unprefixed tool name (e.g., "run_command")
- `request_size_bytes` (int): Size of serialized request parameters
- `response_size_bytes` (int): Size of serialized response
- `duration_ms` (int): Wall-clock time from call start to completion
- `error_code` (string, optional): If failed, the error type (e.g., "tool_not_found", "execution_error", "timeout")
- `argument_keys` (array of string): Always included; keys of the arguments dict
- `arguments` (object, optional): Full argument dict; only when user enables "Show full arguments" toggle
- `arguments_redacted` (bool): `true` if keys-only mode is active

**Current logging site:**
- `SocketServer.handleGatewayCall()` (line 548-602) — logs at info level but passes no metadata

#### 2. Process Lifecycle Metadata
Every process start/stop/crash log must include:
- `command` (string): Command path (e.g., "/usr/bin/env python3")
- `arguments` (array of string): Command arguments
- `pid` (int): Process ID (on start; on stop/crash may be historical)
- `version` (string): From manifest.version
- `exit_code` (int, on stop/crash): Process exit status
- `signal` (string, optional, on crash): Signal name if killed by signal (e.g., "SIGTERM", "SIGKILL")
- `state_transition` (string): Previous state → new state (e.g., "idle → starting")

**Current logging sites:**
- `ProcessManager.start()` (lines 46-162): logs .info "Starting", "Started", or .error "Failed to start" — no metadata
- `ProcessManager.stop()` (lines 164-~220): logs .info "Stopping" — no metadata
- Monitoring/crash detection (Phase 4.3): will log on unexpected termination

#### 3. Gateway Discovery Metadata
Every `gateway_discover` operation must include:
- `mcp_count` (int): Number of MCPs checked
- `tool_count` (int): Total tools discovered
- `duration_ms` (int): Wall-clock time from discovery start to completion
- `mcp_names` (array of string, optional): List of MCPs queried (useful for debugging)

**Current logging site:**
- `SocketServer.handleGatewayDiscover()` (line 521-545) — logs at info level, no metadata except tool_count

#### 4. Socket Operation Metadata
Socket I/O logs must include:
- `method` (string): Socket method name (e.g., "gateway_call", "gateway_discover", "status")
- `bytes_sent` (int): Request payload size
- `bytes_received` (int): Response payload size
- `duration_ms` (int): Round-trip time (request send → response received)
- `client_count` (int): Number of active socket clients at time of operation

**Current logging sites:**
- `ShipyardSocket.send()` (lines 17-131):
  - Line 91: sends request — logs bytes sent
  - Line 101: reads response — logs bytes read
  - Line 115: completion — logs total bytes and duration_ms
- All use `bridgeLog.log()` with partial metadata

#### 5. Tool Enable/Disable Metadata
Every tool or MCP enable/disable operation must include:
- `operation` (string): "enable" or "disable"
- `scope` (string): "tool" or "mcp"
- `target_name` (string): Tool name or MCP name
- `previous_state` (bool): Was it enabled before?
- `new_state` (bool): Is it enabled after?
- `affected_tool_count` (int, if MCP-level): How many tools changed state

**Current logging site:**
- `SocketServer.handleGatewaySetEnabled()` (line 605-624) — no logging currently

#### 6. Configurable Argument Logging Toggle

A **UI toggle in the System Log tab toolbar** (not buried in settings):
- **Default (off):** Log `argument_keys` only, set `arguments_redacted: true`
- **Enabled (on):** Log full `arguments` dict
- **Persistence:** Saved in UserDefaults as `"com.shipyard.logs.show_full_arguments"` (bool)
- **UI placement:** System Log tab header/toolbar, next to existing "Relative time" and "Reveal in Finder" buttons
- **Label:** "Show Arguments" or "Full Arguments" (brief, checkbox style)

**Behavior:**
- When OFF (default):
  ```json
  {
    "mcp_name": "mac-runner",
    "tool_name": "mac-runner__run_command",
    "argument_keys": ["path", "timeout"],
    "arguments_redacted": true
  }
  ```
- When ON:
  ```json
  {
    "mcp_name": "mac-runner",
    "tool_name": "mac-runner__run_command",
    "arguments": {
      "path": "/var/tmp/script.sh",
      "timeout": 30
    },
    "arguments_redacted": false
  }
  ```

### Nice to Have (Post-MVP)

1. **Metadata search/filter in UI:** Allow filtering logs by duration range (e.g., show only calls >1s), or by argument key presence
2. **Metrics dashboard:** Display p50/p95/p99 latencies per tool over time
3. **Export metadata separately:** Option to export only metadata as CSV for analysis
4. **Sampling:** In high-volume scenarios (debug logging), sample every Nth entry to reduce log volume while keeping metadata

---

## Design Decisions

### Metadata Schema: AnyCodableValue vs Rich Types
**Decision:** Keep metadata values as `AnyCodableValue` (string, int, double, bool) as defined in BridgeLogEntry.

**Rationale:** Already parsed correctly by SystemLogView.metaView(); avoids adding complex array/dict support to AnyCodableValue just for this feature.

**Alternative:** Define a richer schema. **Rejected** — would require UI changes to render nested objects.

### Keys-Only Default
**Decision:** Argument logging defaults to keys-only (`arguments_keys`, `arguments_redacted: true`).

**Rationale:**
- User quote: "It's a local tool but logs are in the file... make it configurable but this should be a UI checkmark"
- Keys reveal intent (what args were passed) without exposing sensitive values
- Logs go to disk (~/.shipyard/logs/bridge.jsonl, app.jsonl) — accessible to other processes on the system
- Toggle in UI makes it obvious the feature exists and easily accessible

### Where Metadata is Added
**Decision:** Add metadata at logging call sites, not in logger code.

**Rationale:** Each site knows its context (duration, size, state transitions). Logger would need to infer or require extra parameters.

### Backward Compatibility
**Decision:** Old entries without metadata (before this spec) display as "(no metadata)" without error.

**Rationale:** JSONL files are immutable and grow indefinitely. Old entries won't be retroactively enhanced. UI handles `meta: nil` gracefully (line 358-363 in SystemLogView.swift).

---

## Metadata Audit: All Logging Call Sites

### Category: gateway (ShipyardBridge)

#### MCPServer.swift

**Line ~335** (gateway refresh in discoverTools):
```swift
bridgeLog.log(.info, cat: "init", msg: "gateway refresh: \(gatewayTools.count) tools discovered",
              meta: ["tool_count": gatewayTools.count])
```
**Current metadata:** `tool_count` only
**Required update:** Add:
- `mcp_name`: Server name
- `duration_ms`: Time elapsed since discovery start
- `mcp_count`: Always 1 (local refresh)

---

### Category: socket (ShipyardBridge)

#### ShipyardSocket.swift

**Line 87:** Request write failed
```swift
bridgeLog.log(.error, cat: "socket", msg: "write failed for \(method)")
```
**Current metadata:** None
**Required update:** Add:
- `method`: Already in message, add to meta
- `error_code`: e.g., "write_failed"

**Line 91:** Request written successfully
```swift
bridgeLog.log(.info, cat: "socket", msg: "sent \(written)B for \(method)",
              meta: ["method": method, "bytes": written])
```
**Current metadata:** `method`, `bytes` (sent)
**Required update:** Rename `bytes` to `bytes_sent`. Keep as-is; adequate.

**Line 101:** Response chunk read
```swift
bridgeLog.log(.debug, cat: "socket", msg: "read=\(bytesRead) total=\(totalSoFar)",
              meta: ["method": method, "bytes_read": bytesRead, "total": totalSoFar])
```
**Current metadata:** `method`, `bytes_read`, `total`
**Note:** Debug-level; summarized in line 115. No change needed.

**Line 115:** Response received complete
```swift
bridgeLog.log(.info, cat: "socket", msg: "total \(responseData.count)B for \(method)",
              meta: ["method": method, "bytes": responseData.count, "duration_ms": durationMs])
```
**Current metadata:** `method`, `bytes` (response), `duration_ms`
**Required update:** Rename `bytes` to `bytes_received`. Compute and add:
- `bytes_sent`: From line 91 (requires refactoring ShipyardSocket.send to track or plumb through)
- `client_count`: Snapshot of active clients from SocketServer (requires plumbing)

**Line 110:** Empty response error
```swift
bridgeLog.log(.error, cat: "socket", msg: "empty response for \(method)")
```
**Current metadata:** None
**Required update:** Add:
- `method`: Already in message
- `error_code`: "empty_response"

**Line 121:** JSON parse failed
```swift
bridgeLog.log(.error, cat: "socket", msg: "JSON parse failed for \(method)",
              meta: ["method": method, "response_preview": String(preview)])
```
**Current metadata:** `method`, `response_preview`
**Required update:** Add:
- `error_code`: "json_parse_error"

---

### Category: socket (SocketServer, Shipyard.app)

#### SocketServer.swift

**Line 206:** Server started
```swift
appLogger?.log(.info, cat: "socket-server", msg: "Socket server started",
               meta: ["path": .string(socketPath)])
```
**Current metadata:** `path`
**Reclassify to:** `socket-lifecycle` (not gateway). Note: move to new category or keep in socket.

**Line 212:** Server stopped
```swift
appLogger?.log(.info, cat: "socket-server", msg: "Socket server stopped")
```
**Current metadata:** None
**Required update:** Add:
- `client_count`: Number of active clients at stop time

**Line 308:** Invalid request format
```swift
appLogger?.log(.debug, cat: "socket-server", msg: "Request: (invalid format)")
```
**Current metadata:** None
**Required update:** Add:
- `error_code`: "invalid_request_format"

**Line 312:** Valid request received (info level)
```swift
appLogger?.log(.debug, cat: "socket-server", msg: "Request: \(method)")
```
**Current metadata:** None; already has method in message
**Required update:** Add:
- `method`: Already in message, move to meta
- `client_count`: Active clients

**Line 543:** Gateway discovery complete
```swift
appLogger?.log(.info, cat: "socket-server", msg: "Gateway discovery complete",
               meta: ["tool_count": .int(toolCount)])
```
**Current metadata:** `tool_count`
**Required update:** Add:
- `mcp_count`: Number of MCPs discovered from
- `duration_ms`: Discovery elapsed time

**Line 561:** Gateway call started
```swift
appLogger?.log(.info, cat: "socket-server", msg: "Gateway call: \(toolName)")
```
**Current metadata:** None; tool name in message
**Required update:** Add:
- `tool_name`: Prefixed (e.g., "mac-runner__run_command")
- `mcp_name`: From tool lookup
- `argument_keys`: Extract from params["arguments"]
- `arguments`: (conditionally, based on toggle)
- `arguments_redacted`: (bool)

---

### Category: process (ProcessManager, Shipyard.app)

#### ProcessManager.swift

**Line 49:** Process start initiated
```swift
appLogger?.log(.info, cat: "process", msg: "Starting \(manifest.name)")
```
**Current metadata:** None
**Required update:** Add:
- `mcp_name`: From manifest
- `command`: manifest.command (the executable)
- `arguments`: manifest.args (array)
- `state_transition`: "idle → starting"

**Line 104:** Process started successfully
```swift
appLogger?.log(.info, cat: "process", msg: "Started \(manifest.name)",
               meta: ["pid": .int(Int(process.processIdentifier))])
```
**Current metadata:** `pid`
**Required update:** Add:
- `mcp_name`: From manifest
- `version`: From manifest.version
- `command`: manifest.command
- `arguments`: manifest.args
- `state_transition`: "starting → running"

**Line 158:** Process start failed
```swift
appLogger?.log(.error, cat: "process", msg: "Failed to start \(manifest.name)",
               meta: ["error": .string(error.localizedDescription)])
```
**Current metadata:** `error` (message)
**Required update:** Add:
- `mcp_name`: From manifest
- `error_code`: "start_failed" (standardized)
- `error_detail`: From localizedDescription
- `state_transition`: "starting → error"

**Line 169:** Process stop initiated
```swift
appLogger?.log(.info, cat: "process", msg: "Stopping \(manifest.name)")
```
**Current metadata:** None
**Required update:** Add:
- `mcp_name`: From manifest
- `state_transition`: "running → stopping"

Stopping log entries (on successful stop):
```swift
// Not shown in provided excerpt, but likely exists
appLogger?.log(.info, cat: "process", msg: "Stopped \(manifest.name)")
```
**Required update:** Add:
- `mcp_name`: From manifest
- `pid`: From process dict (before removal)
- `exit_code`: From process.terminationStatus
- `state_transition`: "stopping → idle"

Crash/unexpected termination (Phase 4.3 monitoring):
```swift
// Not yet implemented; to be added in Phase 4.3
appLogger?.log(.error, cat: "process", msg: "Crashed: \(manifest.name)")
```
**Required metadata:**
- `mcp_name`: From manifest
- `pid`: From monitoring tracker
- `exit_code`: From wait4() or process termination
- `signal`: If killed by signal (extract from exit code)
- `state_transition`: "running → error"
- `duration_since_start_ms`: Uptime

---

### Summary Table: All Logging Sites by Category

| File | Line(s) | Level | Message | Current Meta | Status | Add |
|------|---------|-------|---------|--------------|--------|-----|
| ShipyardSocket.swift | 87 | error | write failed | none | **Needs update** | method, error_code |
| ShipyardSocket.swift | 91 | info | sent X bytes | method, bytes | Rename bytes → bytes_sent | method, bytes_sent |
| ShipyardSocket.swift | 110 | error | empty response | none | **Needs update** | method, error_code |
| ShipyardSocket.swift | 115 | info | total X bytes | method, bytes, duration_ms | Rename bytes → bytes_received | bytes_sent (requires refactoring), client_count |
| ShipyardSocket.swift | 121 | error | JSON parse failed | method, response_preview | **Needs update** | error_code |
| SocketServer.swift | 206 | info | Socket server started | path | OK | – |
| SocketServer.swift | 212 | info | Socket server stopped | none | **Needs update** | client_count |
| SocketServer.swift | 308 | debug | Invalid request | none | **Needs update** | error_code |
| SocketServer.swift | 312 | debug | Request received | none | **Needs update** | method, client_count |
| SocketServer.swift | 543 | info | Gateway discovery | tool_count | **Needs update** | mcp_count, duration_ms |
| SocketServer.swift | 561 | info | Gateway call | none | **Needs update** | tool_name, mcp_name, argument_keys, arguments (conditional), arguments_redacted |
| MCPServer.swift | ~335 | info | gateway refresh | tool_count | **Needs update** | mcp_name, duration_ms, mcp_count |
| ProcessManager.swift | 49 | info | Starting | none | **Needs update** | mcp_name, command, arguments, state_transition |
| ProcessManager.swift | 104 | info | Started | pid | **Needs update** | mcp_name, version, command, arguments, state_transition |
| ProcessManager.swift | 158 | error | Failed to start | error | **Needs update** | mcp_name, error_code, error_detail, state_transition |
| ProcessManager.swift | 169 | info | Stopping | none | **Needs update** | mcp_name, state_transition |
| ProcessManager.swift | TBD | info | Stopped | TBD | **To be added** | mcp_name, pid, exit_code, state_transition |
| ProcessManager.swift | TBD | error | Crashed | TBD | **To be added** | mcp_name, pid, exit_code, signal, state_transition, duration_since_start_ms |
| SocketServer.swift | 605-624 | (none) | [set enabled/disabled] | none | **No logging** | Add new logging calls for enable/disable |

---

## Metadata Schema: Complete Reference

### Global Fields (all entries)
- `ts` (string): ISO 8601 timestamp — already logged
- `level` (string): debug, info, warn, error — already logged
- `cat` (string): Category (gateway, socket, process, socket-server, etc.) — already logged
- `src` (string): Source (bridge, app, or MCP name) — already logged
- `msg` (string): Human-readable message — already logged
- `meta` (object, optional): Additional context — **to be populated**

### Metadata by Category

#### gateway_call
```json
{
  "mcp_name": "mac-runner",
  "tool_name": "mac-runner__run_command",
  "original_tool_name": "run_command",
  "request_size_bytes": 245,
  "response_size_bytes": 512,
  "duration_ms": 150,
  "error_code": null,
  "argument_keys": ["path", "timeout"],
  "arguments": { "path": "/tmp/script.sh", "timeout": 30 },
  "arguments_redacted": false
}
```

#### gateway_discover
```json
{
  "mcp_count": 3,
  "mcp_names": ["mac-runner", "bash-tools", "file-ops"],
  "tool_count": 42,
  "duration_ms": 285
}
```

#### process_start
```json
{
  "mcp_name": "mac-runner",
  "command": "/usr/bin/env",
  "arguments": ["python3", "mcp.py"],
  "version": "1.0.0",
  "pid": 18472,
  "state_transition": "idle → starting"
}
```

#### process_stop
```json
{
  "mcp_name": "mac-runner",
  "pid": 18472,
  "exit_code": 0,
  "state_transition": "stopping → idle"
}
```

#### process_crash
```json
{
  "mcp_name": "mac-runner",
  "pid": 18472,
  "exit_code": 139,
  "signal": "SIGSEGV",
  "state_transition": "running → error",
  "duration_since_start_ms": 45000
}
```

#### socket_write
```json
{
  "method": "gateway_call",
  "bytes_sent": 245,
  "error_code": null
}
```

#### socket_read
```json
{
  "method": "gateway_call",
  "bytes_received": 512,
  "duration_ms": 150,
  "error_code": null
}
```

#### tool_enable/disable
```json
{
  "operation": "enable",
  "scope": "tool",
  "target_name": "mac-runner__run_command",
  "previous_state": false,
  "new_state": true,
  "affected_tool_count": 1
}
```

---

## UI Implementation

### System Log Tab Toolbar

Add a new toggle in the filter bar (after "Relative time" button, before "Reveal in Finder"):

```
[Clock Toggle] [New Toggle: "Full Arguments"] [Reveal in Finder] [Open Terminal] [Export] [Refresh] [Clear]
```

**Toggle Component:**
- Label: "Full Arguments" (or "Show Full Arguments")
- Style: Checkbox-style button with gear/settings icon (optional)
- State: Bound to UserDefaults key "com.shipyard.logs.show_full_arguments" (bool, default: false)
- Help text: "Include full argument values in metadata (default: keys only for privacy)"

**Code location:** SystemLogView.swift, in the `filterBar` subview, new ToolbarItem.

### Metadata Display

The existing `metaView(for: entry)` function already displays metadata as a formatted key-value table (lines 341-364). No changes needed to the display logic; it will automatically render the new metadata fields when they're populated.

---

## Implementation Plan

### Phase 1: Argument Logging Toggle + Infrastructure
1. Add UserDefaults key + toggle button in SystemLogView
2. Create AppLogger helper to conditionally include arguments in metadata:
   ```swift
   func extractArgumentMetadata(
     from params: [String: Any],
     includeValues: Bool
   ) -> [String: AnyCodableValue]
   ```
3. Update SocketServer.handleGatewayCall() to call this helper and include in meta
4. Test: Toggle on/off, verify metadata in expanded log entries

### Phase 2: Gateway Operation Metadata
1. Add duration tracking to gateway_call and gateway_discover paths (start time → log time)
2. Update SocketServer.handleGatewayCall() and handleGatewayDiscover() to compute and log duration_ms
3. Add mcp_name, tool_name, mcp_count to respective metadata
4. Update ShipyardSocket.send() to plumb bytes_sent + client_count (requires SocketServer coordination)
5. Test: Trigger gateway calls, verify metadata in logs

### Phase 3: Process Lifecycle Metadata
1. Track process start time, command, arguments in ProcessManager
2. Add state_transition, command, arguments, version to all process logs
3. Add exit_code and signal handling for process termination
4. Implement crash detection logging (Phase 4.3 dependency)
5. Test: Start/stop processes, verify metadata in logs

### Phase 4: Socket Operation Metadata (SocketServer side)
1. Track client_count in SocketServer
2. Add client_count to socket operation logs
3. Add error_code standardization for socket errors
4. Test: Socket requests, verify client_count and error_code in metadata

### Phase 5: Tool Enable/Disable Metadata
1. Add logging calls to handleGatewaySetEnabled() (currently no logging)
2. Include operation, scope, target_name, previous_state, new_state, affected_tool_count
3. Test: Enable/disable tools, verify logs

### Incremental Integration
- Phases can be done in parallel if dependencies allow
- Each phase has clear test points and doesn't break existing functionality
- Old logs (without metadata) remain readable; no migration needed

---

## Acceptance Criteria

### Functional

- [ ] Argument logging toggle appears in System Log tab toolbar (not in settings)
- [ ] Toggle defaults to OFF (keys-only mode)
- [ ] Toggle state persists across app restarts (UserDefaults)
- [ ] When OFF: metadata includes `argument_keys` and `arguments_redacted: true`
- [ ] When ON: metadata includes full `arguments` dict and `arguments_redacted: false`
- [ ] All gateway_call entries include: mcp_name, tool_name, duration_ms, argument_keys, (conditional) arguments
- [ ] All gateway_discover entries include: mcp_count, tool_count, duration_ms
- [ ] All process start entries include: mcp_name, command, arguments, version, pid, state_transition
- [ ] All process stop entries include: mcp_name, pid, exit_code, state_transition
- [ ] All process crash entries include: mcp_name, pid, exit_code, signal, duration_since_start_ms, state_transition
- [ ] All socket operation entries include: method, bytes_sent, bytes_received, duration_ms, error_code (if error)
- [ ] Tool enable/disable operations are logged with: operation, scope, target_name, previous_state, new_state, affected_tool_count
- [ ] Expanded metadata displays as formatted key-value table (existing UI)
- [ ] Old log entries without metadata still show "(no metadata)" without error (backward compatible)

### Non-Functional

- [ ] Metadata adds ≤ 5% overhead to logging operations (duration measurement, dict construction)
- [ ] Toggle click response time ≤ 50ms
- [ ] Log entries with metadata still serialize to JSONL correctly
- [ ] No change to log file rotation behavior or performance

### Coverage

- [ ] Unit tests:
  - Argument metadata extraction (keys-only vs. full)
  - Metadata serialization to AnyCodableValue
  - State transition formatting
  - UserDefaults toggle persistence
- [ ] Integration tests:
  - End-to-end gateway_call with metadata
  - Process lifecycle (start → running → stop) with state transitions
  - Toggle on/off, verify metadata in next log entries
  - Old entries (meta: nil) render without crashing
- [ ] Manual tests:
  - 5+ gateway calls with metadata visible in UI
  - Toggle on/off mid-session, verify next entries reflect change
  - Export logs with metadata, verify JSONL format
  - Inspect process logs for crashes (when Phase 4.3 implemented)

---

## Backward Compatibility

### Old Entries (meta: nil)
- Already handled by SystemLogView.metaView() (lines 358-363): displays "(no metadata)"
- No migration needed; files are immutable

### New Logging Calls with Metadata
- Existing code that doesn't pass metadata continues to work (metadata is optional)
- New code adds metadata field to AnyCodableValue dict
- Serialization to JSONL unchanged

### UI Changes
- New toggle is non-breaking; default OFF preserves current behavior
- Expanded entries continue to display as before, with additional metadata fields

---

## Performance Impact Analysis

### Logging Overhead
- Argument extraction: O(n) where n = number of keys (typically 1-5) → <1ms
- Metadata dict construction: O(n) → <1ms
- Serialization to AnyCodableValue: O(n) → <1ms
- **Total: ≤5ms per entry, acceptable for info-level logging**

### Log File Size
- Gateway call metadata: ~150 bytes (mcp_name, tool_name, duration, keys)
- Process lifecycle: ~100 bytes (command, pid, version, state_transition)
- **Estimate: 20-40% increase in log file size (50 MB max → 60-70 MB max)**
- **No impact on log rotation logic; same 10 MB per file threshold**

### UI Responsiveness
- Toggle state change: writes to UserDefaults, no UI rebuild needed
- Display of metadata: existing code path, no change
- Filtering by metadata: future enhancement, not in MVP

---

## Unknowns & Risks

### Unknown: Client Count Accuracy
**What:** Tracking active client count in SocketServer for socket operation metadata.
**Risk:** Clients can connect/disconnect asynchronously. Count at log time may not reflect count during request processing.
**Mitigation:** Log the count at the moment the log is written (best effort). Document that it's approximate.

### Unknown: Phase 4.3 Process Monitoring
**What:** Detecting unexpected process crashes (SIGSEGV, etc.) and logging with exit code + signal.
**Risk:** Requires Darwin process monitoring (wait4, SIGCHLD handling). Not yet implemented.
**Mitigation:** This spec defines the *schema* for crash logs. Implementation deferred to Phase 4.3.

### Risk: Argument Values Exposure
**What:** If user enables "Full Arguments" toggle, sensitive values (API keys, paths with PII) may be logged to disk.
**Risk:** Log files are stored as plain text in ~/.shipyard/logs; readable by user and other processes.
**Mitigation:**
- Default to keys-only mode (safe)
- UI label warns: "Full arguments may include sensitive data"
- User must opt-in explicitly
- Not Shipyard's responsibility to sanitize arguments (caller should)

---

## Scope Boundaries

### In Scope
- Metadata capture at logging call sites
- Argument logging toggle in UI
- All categories listed above (gateway, process, socket, discovery, enable/disable)
- Backward compatibility with old entries

### Out of Scope
- Real-time log search/filtering UI (post-MVP)
- Metrics dashboard (p50/p95/p99 latencies)
- Automated argument sanitization
- Log encryption or redaction at rest
- Remote log aggregation

---

## References

- **Spec 003 — Logging & Observability:** Defines BridgeLogEntry schema and three-channel logging
- **SystemLogView.swift:** UI rendering of log entries and metadata (lines 341-364)
- **SocketServer.swift:** Gateway operation handlers (lines 521-624)
- **ProcessManager.swift:** Process lifecycle management (lines 46-230)
- **ShipyardSocket.swift:** Bridge-side socket communication (lines 17-131)

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-26 | AI assistant | Initial draft. All logging sites audited. Metadata schemas defined. MVP scope finalized. |

---

**Specification Owner:** AI assistant
**Implementation Status:** Draft (ready for implementation)
**Target Completion:** Session TBD
