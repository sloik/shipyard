---
id: SPEC-007
priority: 2
layer: 2
type: feature
status: done
after: [SPEC-003]
prior_attempts: []
created: 2026-03-26
---

# System Log Metadata Enrichment

## Problem

The Shipyard logging infrastructure (SPEC-003) defines a metadata field on every `BridgeLogEntry` and provides the UI machinery to display it. However, **100% of logging calls currently pass `nil` for metadata**, resulting in "(no metadata)" appearing when users expand log entries in the System Log tab (⌘3).

The metadata infrastructure is ready and unused. Users cannot inspect operational details (why a call took so long, what arguments were passed, whether it succeeded) without opening separate files or running diagnostics.

## Requirements

- [ ] Add gateway call metadata: mcp_name, tool_name, original_tool_name, request_size_bytes, response_size_bytes, duration_ms, error_code, argument_keys, (conditional) arguments, arguments_redacted
- [ ] Add process lifecycle metadata: command, arguments, pid, version, exit_code, signal, state_transition
- [ ] Add gateway discovery metadata: mcp_count, tool_count, duration_ms, mcp_names
- [ ] Add socket operation metadata: method, bytes_sent, bytes_received, duration_ms, client_count
- [ ] Add tool enable/disable metadata: operation, scope, target_name, previous_state, new_state, affected_tool_count
- [ ] Implement configurable argument logging toggle in System Log toolbar (keys-only by default, full values opt-in)
- [ ] Persist toggle state in UserDefaults as `"com.shipyard.logs.show_full_arguments"`
- [ ] Audit all logging call sites and add metadata at each one
- [ ] Ensure backward compatibility: old entries without metadata still display gracefully

## Acceptance Criteria

- [ ] AC 1: Argument logging toggle appears in System Log tab toolbar (not in settings)
- [ ] AC 2: Toggle defaults to OFF (keys-only mode) and persists across app restarts
- [ ] AC 3: When OFF, metadata includes `argument_keys` array and `arguments_redacted: true`
- [ ] AC 4: When ON, metadata includes full `arguments` dict and `arguments_redacted: false`
- [ ] AC 5: All gateway_call entries include mcp_name, tool_name, duration_ms, argument_keys
- [ ] AC 6: All gateway_discover entries include mcp_count, tool_count, duration_ms
- [ ] AC 7: All process start entries include mcp_name, command, arguments, version, pid, state_transition
- [ ] AC 8: All process stop entries include mcp_name, pid, exit_code, state_transition
- [ ] AC 9: All process crash entries include mcp_name, pid, exit_code, signal, duration_since_start_ms, state_transition
- [ ] AC 10: All socket operation entries include method, bytes_sent, bytes_received, duration_ms, error_code (if error)
- [ ] AC 11: Tool enable/disable operations are logged with operation, scope, target_name, previous_state, new_state, affected_tool_count
- [ ] AC 12: Expanded metadata displays as formatted key-value table (existing UI path)
- [ ] AC 13: Old log entries without metadata display "(no metadata)" without error (backward compatible)
- [ ] AC 14: Metadata adds ≤5% overhead to logging operations
- [ ] AC 15: Toggle click response time ≤50ms
- [ ] AC 16: Log entries serialize to JSONL correctly with metadata

## Context

**Code locations:**
- `Shipyard/Views/SystemLogView.swift` — UI rendering of log entries and metadata; toolbar filter bar (where toggle button goes)
- `Shipyard/Models/BridgeLogEntry.swift` — BridgeLogEntry schema with metadata field
- `Shipyard/Services/SocketServer.swift` — Gateway operation handlers (handleGatewayCall, handleGatewayDiscover, handleGatewaySetEnabled)
- `Shipyard/Services/ProcessManager.swift` — Process lifecycle management (start, stop, crash detection)
- `ShipyardBridgeLib/ShipyardSocket.swift` — Bridge-side socket communication (send/receive operations)
- `ShipyardBridgeLib/MCPServer.swift` — Local gateway refresh logging
- `Shipyard/Models/MCPManifest.swift` — Manifest schema for process metadata

**Related specs:**
- SPEC-003 (Logging & Observability) — defines BridgeLogEntry schema and three-channel logging infrastructure

**Performance constraints:**
- Argument extraction: O(n) where n = number of keys (typically 1-5) → <1ms
- Log file size increase: estimate 20-40% (50 MB max → 60-70 MB max); no impact on rotation logic

**Storage:**
- Log files: `~/.shipyard/logs/bridge.jsonl` and `app.jsonl`
- UserDefaults key: `"com.shipyard.logs.show_full_arguments"` (bool)

## Scenarios

1. **Gateway call with arguments inspection:** User calls a tool via gateway → System Log shows metadata with tool_name, duration_ms, argument_keys → user toggles "Show Arguments" → next call shows full arguments in metadata → user can trace why a call took 2s.

2. **Process lifecycle tracking:** User starts an MCP → System Log shows process metadata (mcp_name, pid, version, state_transition: "idle → starting") → process runs → log shows state_transition: "starting → running" → user stops process → log shows exit_code and duration since start.

3. **Discovery latency diagnosis:** User triggers gateway_discover → metadata shows tool_count: 42, duration_ms: 285, mcp_count: 3 → user can identify if discovery is slow due to number of MCPs.

4. **Socket operation forensics:** Low-level socket operation fails → metadata includes method, bytes_sent, error_code: "json_parse_error" → user can debug serialization issues.

5. **Toggle persistence:** User enables "Show Arguments" toggle → restarts app → toggle state is saved in UserDefaults → toggle is still ON on restart.

## Out of Scope

- Metadata search/filter UI (post-MVP enhancement)
- Metrics dashboard with p50/p95/p99 latencies per tool
- Automated argument sanitization or redaction
- Log encryption at rest
- Remote log aggregation
- Export metadata separately as CSV (future)
- Sampling for high-volume scenarios (future)

## Notes for the Agent

**Implementation strategy:**
- Phase 1: Add UserDefaults toggle + helper function to extract argument metadata conditionally
- Phase 2: Add duration tracking to gateway operations; update SocketServer.handleGatewayCall() and handleGatewayDiscover()
- Phase 3: Add process lifecycle metadata (command, arguments, version, state_transition) to all process logs
- Phase 4: Add client_count tracking in SocketServer; standardize socket error codes
- Phase 5: Add logging calls to handleGatewaySetEnabled() (currently no logging at all)

**Testing approach:**
- Unit tests: Argument extraction (keys-only vs. full), metadata serialization, state_transition formatting, UserDefaults persistence
- Integration tests: End-to-end gateway_call with metadata, process lifecycle (start → running → stop), toggle on/off verification, old entries (meta: nil) rendering without crash
- Manual tests: 5+ gateway calls visible in UI, toggle on/off mid-session, export logs and verify JSONL format

**Key gotchas:**
- Old entries (before this spec) will have `meta: nil`; SystemLogView.metaView() already handles this (lines 358-363) — no migration needed
- Client count tracking in SocketServer requires care: clients can connect/disconnect asynchronously. Log the count at the moment the log is written (best effort).
- Argument values may contain sensitive data (API keys, paths with PII). Default to keys-only; user must opt-in explicitly for full values.
- Phase 4.3 process monitoring (crash detection) is a soft dependency — crash log schema defined here, implementation deferred.

**Watch out for:**
- N+1 metadata lookups: each logging site should construct metadata locally, not fetch from elsewhere
- Metadata dict serialization: ensure AnyCodableValue handles all field types (string, int, bool, array of strings)
- Toggle UI placement: must be in System Log tab toolbar (next to "Relative time" button), not buried in settings
