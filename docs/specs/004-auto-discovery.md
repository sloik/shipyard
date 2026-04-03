# Spec 004: Auto-Discovery of Child MCPs

**Status:** Draft
**Version:** 0.1
**Last Updated:** 2026-03-25
**Author:** AI assistant
**Deciders:** project maintainer, AI assistant
**Related:** Spec 001 (Server Management §4.6), Spec 002 (Gateway §Discovery triggers), ADR 0003

---

## Problem Statement

Adding a new child MCP to Shipyard currently requires a manual step: either clicking Refresh (⌘R) in the UI or restarting the app. This friction breaks the flow when a user drops a new `manifest.json` into the discovery directory and expects it to just appear.

**Current behavior:**
1. `MCPRegistry.discover()` runs once at app startup
2. Scans `~/code/mcp/*/manifest.json`
3. Registers found servers
4. **No file watching.** New manifests are invisible until manual refresh.

**ShipyardBridge adds a second layer of staleness:**
1. `ShipyardBridge.MCPServer.init()` calls `refreshGatewayTools()` once at startup
2. Caches `gatewayTools` (tools from all child MCPs)
3. **No re-discovery.** Even if Shipyard.app re-discovers, the bridge's cached tool list is stale until bridge restart.

**Result:** Adding lmac-run today = drop files + restart Shipyard + restart bridge. Should be: drop files, done.

---

## Vision

**Shipyard watches the discovery directory for changes and automatically registers/deregisters child MCPs.** New manifests appear in the UI within seconds. ShipyardBridge's tool list stays in sync.

```
User drops lmac-run-mcp/manifest.json
        │
        ▼ (FSEvents, <2s)
MCPRegistry detects new directory
        │
        ▼
MCPManifest.load() → MCPServer created
        │
        ▼
UI updates (new server visible, idle state)
        │
        ▼ (if auto-start enabled, optional)
ProcessManager.start() → MCPBridge created
        │
        ▼
GatewayRegistry.updateTools() → new tools registered
        │
        ▼ (socket notification)
ShipyardBridge.refreshGatewayTools() → Claude sees new tools
```

---

## Requirements

### Must Have

#### 1. Directory Watcher (FSEvents)

- Watch the discovery path (`~/code/mcp/`) for filesystem changes
- Use macOS FSEvents API (via `DispatchSource.makeFileSystemObjectSource` or `FileManager` + `DispatchSource`)
- Debounce: coalesce changes within a 1-second window (Dropbox sync can trigger multiple events)
- Trigger `MCPRegistry.rescan()` on change

**Target file:** `Shipyard/Services/DirectoryWatcher.swift` (new)

#### 2. MCPRegistry.rescan() — Incremental Discovery

- Compare current registry against filesystem scan
- **New manifest found:** create MCPServer, add to registry, notify UI
- **Manifest removed:** if server is idle, remove from registry. If running, mark as "orphaned" (warn in UI, don't kill)
- **Manifest changed:** if server is idle, reload manifest. If running, flag "config changed, restart to apply"
- Thread-safe: runs on MainActor (same as existing `discover()`)

**Target file:** `Shipyard/Services/MCPRegistry.swift` (modify)

#### 3. GatewayRegistry Sync on MCP Lifecycle

- When a new MCP starts → call `MCPBridge.discoverTools()` → update `GatewayRegistry`
- When an MCP stops → remove its tools from `GatewayRegistry`
- This already partially exists (Spec 002, §Discovery triggers). Ensure it fires on auto-discovered MCPs too.

**Target file:** `Shipyard/Models/GatewayRegistry.swift` (verify/modify)

#### 4. ShipyardBridge Tool List Refresh

- Add a socket method: `tools_changed` notification (Shipyard.app → ShipyardBridge)
- When `GatewayRegistry` tools change, Shipyard.app sends `tools_changed` via socket
- ShipyardBridge receives notification and calls `refreshGatewayTools()`
- Claude sees updated tool list on next `tools/list` call

**Target files:**
- `Shipyard/Services/SocketServer.swift` (add notification sender)
- `ShipyardBridgeLib/MCPServer.swift` (add notification listener + refresh)

#### 5. MCP Protocol `tools/list_changed` Notification

- After ShipyardBridge refreshes its tool list, it should send `notifications/tools/list_changed` to Claude via stdout
- This is a standard MCP 2.0 notification that tells the client to re-fetch `tools/list`
- Claude Desktop / Claude Code will then call `tools/list` and get the updated list

**Target file:** `ShipyardBridgeLib/MCPServer.swift` (add notification emission)

### Nice to Have (Post-MVP)

1. **Auto-start policy:** manifest field `"auto_start": true` — new MCPs start automatically on discovery
2. **Notification toast:** macOS notification when new MCP is discovered ("lmac-run registered")
3. **Manifest validation on watch:** validate JSON before registering (prevent bad manifests from crashing)
4. **Ignore patterns:** `.gitignore`-style exclusion for the watcher (skip `__pycache__`, `.venv`, etc.)

---

## Design Decisions

### FSEvents vs. Polling

**Decision:** FSEvents (macOS native file system events)

**Rationale:**
- Zero CPU cost when idle (kernel pushes events, no polling)
- Sub-second latency (typically <500ms)
- Standard macOS API, well-tested
- Dropbox-compatible (Dropbox uses FSEvents internally)

**Alternative rejected:** Polling (timer-based rescan every N seconds) — wastes CPU, higher latency, no advantage.

### Debounce Window: 1 Second

**Decision:** Coalesce filesystem events within a 1-second window before triggering rescan.

**Rationale:**
- Dropbox sync writes `manifest.json` in stages (create → write → close → xattr)
- Git operations can touch multiple files rapidly
- 1 second is long enough to coalesce, short enough to feel instant

### Orphaned Server Handling

**Decision:** If a running server's manifest disappears from disk, warn but don't kill.

**Rationale:**
- Accidental deletion shouldn't crash a running pipeline
- User might be moving files (rename → brief absence → reappear)
- UI shows warning: "Manifest missing — server will be removed on next stop"

### ShipyardBridge Notification vs. Polling

**Decision:** Push notification via socket (`tools_changed`), not polling.

**Rationale:**
- Immediate propagation (no polling interval latency)
- Zero overhead when nothing changes
- Socket is already established (Shipyard ↔ Bridge communication exists)

**Alternative rejected:** Bridge polls `gateway_discover` every N seconds — wasteful, adds latency.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│  macOS Filesystem                                 │
│  ~/code/mcp/                                     │
│  ├── lmstudio-mcp/manifest.json                  │
│  ├── mac-runner-mcp/manifest.json                │
│  ├── lmac-run-mcp/manifest.json   ← NEW          │
│  └── hear-me-say/manifest.json                   │
└──────────────┬───────────────────────────────────┘
               │ FSEvents
               ▼
┌──────────────────────────────────────────────────┐
│  DirectoryWatcher (new)                           │
│  • Watches discovery path via FSEvents            │
│  • Debounces (1s window)                          │
│  • Calls MCPRegistry.rescan()                     │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│  MCPRegistry.rescan() (modified)                  │
│  • Diff: current registry vs filesystem           │
│  • Add new MCPServers                             │
│  • Mark removed as orphaned                       │
│  • Flag changed manifests                         │
│  @Observable → UI updates automatically           │
└──────────────┬───────────────────────────────────┘
               │ (if MCP starts)
               ▼
┌──────────────────────────────────────────────────┐
│  GatewayRegistry.updateTools()                    │
│  • Calls MCPBridge.discoverTools()                │
│  • Updates namespaced tool catalog                │
│  • Notifies SocketServer of change                │
└──────────────┬───────────────────────────────────┘
               │ socket: tools_changed
               ▼
┌──────────────────────────────────────────────────┐
│  ShipyardBridge                                   │
│  • Receives tools_changed notification            │
│  • Calls refreshGatewayTools()                    │
│  • Emits MCP notifications/tools/list_changed     │
│  → Claude re-fetches tools/list                   │
└──────────────────────────────────────────────────┘
```

---

## Acceptance Criteria

### Directory Watcher

- [ ] AC 1: New `manifest.json` in discovery path triggers `MCPRegistry.rescan()` within 2 seconds
- [ ] AC 2: Deleted manifest directory triggers rescan (server marked orphaned if running, removed if idle)
- [ ] AC 3: Rapid filesystem changes (5 events in 500ms) are debounced into a single rescan
- [ ] AC 4: Watcher survives Dropbox sync storms (100+ xattr changes) without crashing or spinning

### MCPRegistry.rescan()

- [ ] AC 5: New manifest → MCPServer created, visible in UI, state = idle
- [ ] AC 6: Removed manifest (server idle) → server removed from registry
- [ ] AC 7: Removed manifest (server running) → server marked orphaned, warning in UI, not killed
- [ ] AC 8: Changed manifest (server idle) → manifest reloaded with new values
- [ ] AC 9: Changed manifest (server running) → flag "config changed, restart to apply"
- [ ] AC 10: Rescan is idempotent — running twice with no filesystem change produces no state change

### GatewayRegistry Sync

- [ ] AC 11: Auto-discovered MCP starts → its tools appear in GatewayRegistry
- [ ] AC 12: Auto-discovered MCP stops → its tools removed from GatewayRegistry

### ShipyardBridge Refresh

- [ ] AC 13: GatewayRegistry tool change → `tools_changed` notification sent via socket
- [ ] AC 14: ShipyardBridge receives `tools_changed` → refreshes gateway tools
- [ ] AC 15: ShipyardBridge emits `notifications/tools/list_changed` to Claude after refresh
- [ ] AC 16: Claude's next `tools/list` call returns the updated tool set

### Integration

- [ ] AC 17: End-to-end: drop new MCP directory → tools available to Claude without any restart
- [ ] AC 18: End-to-end: remove MCP directory → tools disappear from Claude's tool list
- [ ] AC 19: Existing manual Refresh (⌘R) still works (backward compatible)

---

## Test Strategy

### Unit Tests

| Component | Tests | Key Scenarios |
|-----------|-------|---------------|
| DirectoryWatcher | ~10 | FSEvents callback, debounce, path filtering, start/stop |
| MCPRegistry.rescan() | ~12 | New/removed/changed manifest, orphan handling, idempotency |
| SocketServer (tools_changed) | ~5 | Notification emission, no-listener graceful handling |
| ShipyardBridge (refresh) | ~8 | Notification reception, tool list update, MCP notification emission |

### Integration Tests

- Drop manifest → verify server appears in registry (within 2s)
- Remove manifest → verify idle server removed, running server orphaned
- Full chain: drop manifest → start server → verify tools in gateway → verify bridge refreshed → verify Claude gets updated tools/list

### Manual Tests

- Drop `lmac-run-mcp/` while Shipyard is running → verify it appears
- Delete `lmac-run-mcp/` while its server is running → verify orphan warning
- Dropbox sync conflict (both machines write manifest) → verify no crash

---

## Implementation Plan

### Phase 1: DirectoryWatcher (0.5 day)

1. New file: `Shipyard/Services/DirectoryWatcher.swift`
2. FSEvents-based watcher with debounce
3. Callback: `onDirectoryChanged: () -> Void`
4. Unit tests

### Phase 2: MCPRegistry.rescan() (1 day)

1. Modify `MCPRegistry.swift` — add `rescan()` method
2. Diff logic: compare registered names vs discovered manifests
3. Handle add/remove/change cases
4. Wire up: `DirectoryWatcher.onDirectoryChanged = { registry.rescan() }`
5. Unit tests + integration tests

### Phase 3: ShipyardBridge Notification (0.5 day)

1. Add `tools_changed` socket method to `SocketServer.swift`
2. GatewayRegistry calls it when tools change
3. ShipyardBridge listens for `tools_changed`, calls `refreshGatewayTools()`
4. ShipyardBridge emits `notifications/tools/list_changed` to stdout
5. Unit tests

### Phase 4: Integration Testing (0.5 day)

1. End-to-end tests
2. Manual verification with real MCPs
3. Dropbox compatibility check

**Total estimated:** 2.5 days

---

## Files Affected

| File | Change |
|------|--------|
| `Shipyard/Services/DirectoryWatcher.swift` | **NEW** — FSEvents watcher |
| `Shipyard/Services/MCPRegistry.swift` | **MODIFY** — add `rescan()`, wire watcher |
| `Shipyard/Models/GatewayRegistry.swift` | **VERIFY** — ensure lifecycle triggers work for auto-discovered MCPs |
| `Shipyard/Services/SocketServer.swift` | **MODIFY** — add `tools_changed` notification sender |
| `ShipyardBridgeLib/MCPServer.swift` | **MODIFY** — listen for `tools_changed`, emit MCP notification |
| `ShipyardTests/DirectoryWatcherTests.swift` | **NEW** |
| `ShipyardTests/MCPRegistryRescanTests.swift` | **NEW** |
| `ShipyardBridgeTests/ToolsChangedTests.swift` | **NEW** |

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Dropbox FSEvents flood | Medium | Watcher spins or fires too often | Debounce (1s), ignore non-manifest changes |
| Race: rescan during MCP start | Low | Duplicate registration | MCPRegistry guards against duplicate names |
| Bridge socket disconnected | Low | tools_changed lost | Bridge reconnects; manual Refresh as fallback |
| Large discovery directory | Low | Slow rescan | Only scan immediate subdirs, not recursive |

---

## References

- Spec 001 §4.6 — Registry refresh workflow (manual)
- Spec 002 §Discovery triggers — lists hot-reload as implemented (for MCP lifecycle, not filesystem)
- ADR 0003 — Gateway pattern; single MCP entry point
- Apple FSEvents Programming Guide
- MCP 2.0 Spec — `notifications/tools/list_changed`

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-03-25 | AI assistant | Initial draft |
