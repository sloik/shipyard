---
id: SPEC-004
priority: 2
layer: 2
type: feature
status: done
after: [SPEC-001, SPEC-002]
prior_attempts: []
created: 2026-03-25
---

# Auto-Discovery of Child MCPs

## Problem

Adding a new child MCP to Shipyard currently requires manual intervention: either clicking Refresh (⌘R) in the UI or restarting the app. This friction breaks the flow — when the user drops a new `manifest.json` into the discovery directory, it should appear immediately without manual action.

**Current behavior:**
- `MCPRegistry.discover()` runs once at app startup, scans `~/mcp-servers/*/manifest.json`, and registers found servers
- **No file watching:** New manifests are invisible until manual refresh
- `ShipyardBridge.MCPServer.init()` calls `refreshGatewayTools()` once at startup and caches the result
- **No re-discovery:** Even if Shipyard.app re-discovers, the bridge's cached tool list is stale until bridge restart

**Result:** Adding a new MCP today = drop files + restart Shipyard + restart bridge. Should be: drop files, done.

## Requirements

- [ ] Watch the discovery directory for filesystem changes using macOS FSEvents API
- [ ] Debounce filesystem events within a 1-second window to coalesce Dropbox sync writes
- [ ] Implement `MCPRegistry.rescan()` to incrementally discover/update/remove MCPs based on filesystem changes
- [ ] Handle orphaned servers gracefully: warn if a running server's manifest disappears, but don't force-kill
- [ ] Update `GatewayRegistry` when auto-discovered MCPs start/stop to keep the tool catalog in sync
- [ ] Send `tools_changed` socket notification from Shipyard.app to ShipyardBridge when gateway tools change
- [ ] Have ShipyardBridge listen for `tools_changed`, refresh its tool list, and emit `notifications/tools/list_changed` to Claude
- [ ] Ensure end-to-end: drop new MCP directory → tools available to Claude without any restart (backward compatible with manual Refresh)

## Acceptance Criteria

### Directory Watcher

- [ ] AC 1: New `manifest.json` in discovery path triggers `MCPRegistry.rescan()` within 2 seconds
- [ ] AC 2: Deleted manifest directory triggers rescan; server marked orphaned if running, removed if idle
- [ ] AC 3: Rapid filesystem changes (5 events in 500ms) are debounced into a single rescan
- [ ] AC 4: Watcher survives Dropbox sync storms (100+ xattr changes) without crashing or spinning

### MCPRegistry.rescan()

- [ ] AC 5: New manifest → `MCPServer` created, visible in UI, state = idle
- [ ] AC 6: Removed manifest (server idle) → server removed from registry
- [ ] AC 7: Removed manifest (server running) → server marked orphaned, warning in UI, not killed
- [ ] AC 8: Changed manifest (server idle) → manifest reloaded with new values
- [ ] AC 9: Changed manifest (server running) → flag "config changed, restart to apply"
- [ ] AC 10: Rescan is idempotent — running twice with no filesystem change produces no state change

### GatewayRegistry Sync

- [ ] AC 11: Auto-discovered MCP starts → its tools appear in `GatewayRegistry`
- [ ] AC 12: Auto-discovered MCP stops → its tools removed from `GatewayRegistry`

### ShipyardBridge Refresh

- [ ] AC 13: `GatewayRegistry` tool change → `tools_changed` notification sent via socket
- [ ] AC 14: ShipyardBridge receives `tools_changed` → refreshes gateway tools
- [ ] AC 15: ShipyardBridge emits `notifications/tools/list_changed` to Claude after refresh
- [ ] AC 16: Claude's next `tools/list` call returns the updated tool set

### Integration

- [ ] AC 17: End-to-end: drop new MCP directory → tools available to Claude without any restart
- [ ] AC 18: End-to-end: remove MCP directory → tools disappear from Claude's tool list
- [ ] AC 19: Existing manual Refresh (⌘R) still works (backward compatible)

## Context

**Key files affected:**

- `Shipyard/Services/DirectoryWatcher.swift` — **NEW** FSEvents-based watcher with debounce
- `Shipyard/Services/MCPRegistry.swift` — add `rescan()` method for incremental discovery
- `Shipyard/Models/GatewayRegistry.swift` — verify/modify to ensure lifecycle triggers fire for auto-discovered MCPs
- `Shipyard/Services/SocketServer.swift` — add `tools_changed` notification sender
- `ShipyardBridgeLib/MCPServer.swift` — listen for `tools_changed`, emit MCP notification
- `Shipyard/Services/ProcessManager.swift` — manages MCP process lifecycle
- `Shipyard/Services/MCPBridge.swift` — discovers tools from running MCPs

**Architecture context:**

- Discovery directory: `~/mcp-servers/`
- Each child MCP has a `manifest.json` defining command, args, and metadata
- MCPRegistry is `@Observable` so UI automatically updates on changes
- SocketServer maintains persistent connection between Shipyard.app and ShipyardBridge
- GatewayRegistry namespaces tools by MCP (e.g., `lmstudio__list_models`, `mac_runner__execute`)

**Related specs:**

- SPEC-001 (Server Management §4.6) — Registry refresh workflow (manual)
- SPEC-002 (Gateway §Discovery triggers) — lists hot-reload as implemented for MCP lifecycle, not filesystem
- ADR 0003 — Gateway pattern; single MCP entry point

## Alternatives Considered

**FSEvents vs. Polling:**

- **Chosen: FSEvents** — Zero CPU cost when idle (kernel pushes events), sub-second latency (~500ms), standard macOS API, Dropbox-compatible
- **Rejected: Polling** — Wastes CPU, higher latency, no advantage for this use case

**Debounce Window (1 second):**

- **Chosen: 1 second** — Long enough to coalesce Dropbox writes (create → write → close → xattr) and Git operations, short enough to feel instant
- **Alternative: 0.5 seconds** — Risk of incomplete writes; Git touch 100+ files rapidly
- **Alternative: 2+ seconds** — Feels sluggish; defeats "drop and see" UX

**Orphaned Server Handling:**

- **Chosen: Warn but don't kill** — Accidental deletion shouldn't crash a running pipeline; user might be moving files (rename → brief absence → reappear)
- **Alternative: Force-kill** — Too aggressive; breaks workflows

**ShipyardBridge Notification:**

- **Chosen: Push notification via socket** (`tools_changed`) — Immediate propagation, zero overhead when nothing changes, socket already established
- **Alternative: Bridge polls `gateway_discover`** — Wasteful, adds latency

## Scenarios

1. **Drop new MCP directory:** User drops `lmac-run-mcp/` with manifest.json into discovery directory → within 2 seconds, Shipyard detects it → `MCPRegistry.rescan()` creates new `MCPServer` (idle state) → UI shows it → if auto-start enabled, ProcessManager starts it → GatewayRegistry.updateTools() called → SocketServer sends `tools_changed` → ShipyardBridge refreshes and notifies Claude → Claude's next `tools/list` call includes new tools

2. **Remove MCP directory (idle server):** User deletes `lmac-run-mcp/` directory → FSEvents triggers rescan → `MCPRegistry.rescan()` detects missing manifest → server is idle, so it's removed from registry → GatewayRegistry.updateTools() called → tools removed from gateway → `tools_changed` notified → Claude's next `tools/list` call excludes those tools

3. **Remove MCP directory (running server):** User deletes `lmac-run-mcp/` while server is running → FSEvents triggers rescan → manifest missing but server is still running → marked "orphaned" in registry → UI shows warning "Manifest missing — will be removed on next stop" → tools remain in gateway (to avoid disrupting workflows) → when user stops the server or manually resolves, server removed

4. **Dropbox sync conflict:** Both machines write to `manifest.json` simultaneously → FSEvents fires 10+ events in 100ms (xattr changes, writes) → debouncer coalesces to single rescan within 1s → rescan loads manifest, detects single config change → if server idle, reloads; if running, flags "config changed"

5. **Rapid edits (Git operations):** User runs `git checkout` which touches 5 manifest files → 5+ FSEvents fire in <100ms → debouncer coalesces to single rescan → idempotent rescan processes all changes in one pass

## Out of Scope

- Auto-start policy manifest field (`"auto_start": true`) — nice-to-have, post-MVP
- Notification toast (macOS notification when new MCP discovered) — nice-to-have, post-MVP
- Manifest validation on watch (prevent bad manifests from crashing) — post-MVP
- Ignore patterns (`.gitignore`-style exclusion for watcher) — post-MVP
- Recursive directory scanning of large discovery trees — spec assumes flat structure, each MCP in its own top-level directory

## Notes for the Agent

**Implementation strategy:**

1. **Phase 1: DirectoryWatcher (0.5 day)**
   - Create `Shipyard/Services/DirectoryWatcher.swift` with FSEvents-based watcher
   - Use `DispatchSource.makeFileSystemObjectSource()` or equivalent
   - Implement 1-second debounce via `DispatchSourceTimer`
   - Callback: `onDirectoryChanged: () -> Void`
   - Unit tests for FSEvents callback, debounce coalescing, start/stop

2. **Phase 2: MCPRegistry.rescan() (1 day)**
   - Add `rescan()` method to `MCPRegistry.swift`
   - Diff algorithm: iterate filesystem, compare against `servers` dict
   - New: create `MCPServer`, add to registry, trigger UI update
   - Removed (idle): remove from registry
   - Removed (running): set `isOrphaned = true`, keep in registry, warn in UI
   - Changed (idle): reload manifest
   - Changed (running): set `configChangedFlag`, show "restart to apply"
   - Thread-safe: runs on `@MainActor` (UI updates must be on main thread)
   - Wire up: `directoryWatcher.onDirectoryChanged = { registry.rescan() }`
   - Unit tests + integration tests for each case

3. **Phase 3: ShipyardBridge Notification (0.5 day)**
   - Add `tools_changed` method to `SocketServer.swift`
   - When `GatewayRegistry.toolsByNamespace` changes, call `socketServer.notifyToolsChanged()`
   - Modify `ShipyardBridgeLib/MCPServer.swift` to listen for `tools_changed` on socket
   - On receipt: call `refreshGatewayTools()`
   - After refresh: emit `notifications/tools/list_changed` to stdout (MCP 2.0 standard)
   - Unit tests for socket notification, refresh trigger, Claude notification

4. **Phase 4: Integration Testing (0.5 day)**
   - End-to-end: drop manifest → verify in registry within 2s
   - Remove manifest (both idle and running cases) → verify correct behavior
   - Full chain: drop → start → verify tools in gateway → verify bridge refreshed → verify Claude tools/list
   - Manual: real MCPs (lmac-run, etc.) with Shipyard running

**Known gotchas:**

- FSEvents can fire multiple times for a single logical change (Dropbox writes metadata after data) — debounce is critical
- `MCPRegistry` is `@Observable` so property changes trigger UI updates automatically — don't add manual notifications
- `ProcessManager.start()` is async; rescan must not block waiting for it. Use separate task if needed.
- Test with Dropbox active (simulate actual environment). FSEvents behavior differs between local and network filesystems.
- `ShipyardBridge` is a separate process. Socket communication is the only reliable way to sync state. Don't rely on shared memory.

**Test data/fixtures:**

- Create temporary manifest directories in tests (don't hardcode Dropbox path)
- Mock FSEvents callbacks for unit tests (don't require real filesystem changes during CI)
- See `ShipyardTests/` for existing test patterns

**References:**

- Apple FSEvents Programming Guide (https://developer.apple.com/library/archive/documentation/System/Conceptual/FileSystemEvents_ProgGuide/Introduction/Introduction.html)
- MCP 2.0 Spec: `notifications/tools/list_changed` (https://spec.modelcontextprotocol.io/latest/basic/notifications/)
- Existing code:
  - `MCPRegistry.swift` — current `discover()` method pattern
  - `SocketServer.swift` — existing socket communication for other methods
  - `ShipyardBridgeLib/MCPServer.swift` — current bridge lifecycle and tool discovery
  - `GatewayRegistry.swift` — current tool namespace management
