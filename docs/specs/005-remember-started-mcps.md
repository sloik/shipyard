# Shipyard Auto-Start & Remember State — Specification

> **Version:** 1.0
> **Author:** AI assistant
> **Date:** 2026-03-25
> **Methodology:** Spec-driven development — change this specification before changing tests or code.
> **Status:** Pending implementation
> **Depends on:** SPEC-001 (Server Management), SPEC-002 (Gateway), SPEC-004 (Auto-Discovery)

---

## 1. Goal and Philosophy

Shipyard's Server Management feature (SPEC-001) provides full lifecycle control over MCP servers: start, stop, restart, and real-time monitoring. However, when the app quits (gracefully or via crash) or the Mac reboots, all servers return to idle state. Users must manually restart each one, disrupting workflows.

The **Auto-Start & Remember State** feature persists which servers were running at app shutdown, then automatically restarts them on the next launch. This makes the typical workflow seamless: start lmstudio and mac-runner once, and expect them to remain running across app restarts and reboots.

**Core responsibilities:**
1. **Persistence:** Save the list of running MCP names to UserDefaults on app quit
2. **Recovery:** After MCPRegistry discovery completes on app launch, auto-start all saved MCPs
3. **Settings UI:** Provide ⌘, preferences window with "Restore servers" toggle and auto-start delay configuration
4. **Resilience:** Handle missing MCPs, failed starts, and crash recovery gracefully

**Design principles:**
- UserDefaults for lightweight persistence (consistent with existing GatewayRegistry patterns)
- Sequential start with configurable delay to avoid resource spikes
- Silent removal of MCPs no longer in registry (backward compatible)
- Failures do not block other starts (fail-safe)
- First launch has no saved state (backward compatible)
- Settings UI integrates with macOS standard Preferences shortcut (⌘,)

---

## 2. Core Components

### 2.1 AutoStartManager

**Purpose:** Coordinate persistence, recovery, and sequential startup of auto-started MCPs.

**Responsibilities:**
- Save list of running MCP names to UserDefaults on app quit
- Load saved list from UserDefaults on app launch
- Sequentially start all saved MCPs after MCPRegistry.discover() completes
- Skip MCPs no longer in registry and clean up saved list
- Respect the "Restore servers" setting before starting
- Handle failed starts gracefully (log, continue, update UI)
- Manage auto-start delay setting (configurable 1-10s, default 2s)

**Key properties:**
```
class AutoStartManager: @MainActor {
    let processManager: ProcessManager    // injected
    let registry: MCPRegistry             // injected
    let settings: AutoStartSettings       // loaded from UserDefaults

    // UserDefaults keys
    static let restoreServersKey = "autoStartRestoreServers"    // Bool, default: true
    static let autoStartDelayKey = "autoStartDelay"              // Double (seconds), default: 2.0
    static let lastRunningServersKey = "autoStartLastRunning"    // [String] (MCP names)
}
```

**Key methods:**
```swift
// Called on app quit (or in response to willTerminate signal)
func saveRunningServers(from registry: MCPRegistry) async throws
// 1. Filter registry.servers to those with .running state
// 2. Extract names into [String]
// 3. Save to UserDefaults[lastRunningServersKey]
// 4. Log "Saved N servers for auto-start"

// Called after MCPRegistry.discover() completes on app launch
func autoStartSavedServers() async
// 1. Load restoreServersKey and lastRunningServersKey from UserDefaults
// 2. If restoreServersKey is false, skip (silent, don't start anything)
// 3. If no saved servers or lastRunningServersKey is empty, return
// 4. For each saved server name (in order):
//    a. Look up server in registry.servers by name
//    b. If not found, skip and remove from saved list
//    c. If found, call startOne(server) with delay
//    d. On error, log and continue (don't block others)
// 5. Save cleaned-up list back to UserDefaults

// Internal: start a single server with delay between starts
private func startOne(server: MCPServer) async
// 1. Wait for autoStartDelay (configurable)
// 2. Call processManager.start(server)
// 3. Catch error, log with structured logging: name, error reason
// 4. Don't update UI (ProcessManager will notify via @Observable)

// Load current settings from UserDefaults
func loadSettings() -> AutoStartSettings
// Return settings object with restoreServers and delay

// Save settings to UserDefaults
func saveSettings(_ settings: AutoStartSettings)
// Write restoreServers and delay back to UserDefaults

// For testing: clear saved state
func clearSavedState()
// Delete keys from UserDefaults (test cleanup)
```

**Key decisions:**
- AutoStartManager is @MainActor for thread safety (all UserDefaults access on main thread)
- Start is sequential (not parallel) to avoid resource spikes
- Delay is configurable per user preference, not hardcoded
- Missing MCPs are silently skipped and removed from saved list (don't clutter UserDefaults)
- Failed starts log but don't block subsequent starts (fail-safe)
- No UI blocking during auto-start (background task, async/await)

---

### 2.2 AutoStartSettings Model

**Purpose:** Represent user preferences for auto-start behavior.

**Properties:**
```swift
struct AutoStartSettings: Codable, Equatable {
    var restoreServers: Bool = true           // default: restore on launch
    var autoStartDelay: Double = 2.0           // seconds, range 1.0-10.0
}
```

**Key decisions:**
- Simple Codable struct for JSON serialization (UserDefaults handles encoding)
- Both properties have sensible defaults
- Delay range enforced by UI slider/stepper, not struct (UX concern)

---

### 2.3 SettingsView (SwiftUI)

**Purpose:** Provide preferences UI accessible via ⌘, (macOS standard Preferences shortcut).

**Responsibilities:**
- Render "Restore previously running servers on launch" toggle
- Render "Auto-start delay between servers" slider or stepper (1-10s)
- Bind to UserDefaults via @AppStorage or custom @State + onChange
- Save changes immediately
- Show current values

**Component structure:**
```swift
struct SettingsView: View {
    @State private var settings: AutoStartSettings
    let onSave: (AutoStartSettings) -> Void

    var body: some View {
        Form {
            Section("Server Auto-Start") {
                Toggle("Restore previously running servers on launch",
                       isOn: $settings.restoreServers)
                    .help("If ON: on next launch, Shipyard will automatically start the servers that were running when it quit. If OFF: servers will remain idle until you start them manually.")

                Stepper("Auto-start delay: \(String(format: "%.1f", settings.autoStartDelay))s",
                        value: $settings.autoStartDelay,
                        in: 1...10,
                        step: 0.1)
                    .help("Delay between starting each server (1-10 seconds). Prevents resource spikes when multiple servers start.")
                    .monospacedDigit()
            }
        }
        .onChange(of: settings) { oldValue, newValue in
            if oldValue != newValue {
                onSave(newValue)
            }
        }
    }
}
```

**Key decisions:**
- Form + Section for standard macOS appearance
- Toggle for boolean (clear, discoverable)
- Stepper or Slider for delay (slider preferred for continuous range)
- Help text explains behavior
- Immediate save on change (no "Apply" button)
- Uses .help() for tooltips (native macOS accessibility)

---

### 2.4 ShipyardApp Modifications

**Purpose:** Integrate AutoStartManager into app lifecycle and add Settings window.

**Changes:**
```swift
@main
struct ShipyardApp: App {
    @State private var autoStartManager: AutoStartManager

    var body: some Scene {
        WindowGroup {
            MainWindow()
                .environment(autoStartManager)  // inject for dependency
        }
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button("Preferences…") {
                    NSApp.sendAction(#selector(NSApplication.orderFrontPreferencesPanel(_:)), to: nil, from: nil)
                }
                .keyboardShortcut(",", modifiers: [.command])
            }
        }

        // Settings scene for ⌘, window
        Settings {
            SettingsView(onSave: { settings in
                autoStartManager.saveSettings(settings)
            })
        }
    }

    nonisolated private func setupAppDelegateForQuit() {
        // On willTerminate, call autoStartManager.saveRunningServers()
        // See Lifecycle section for details
    }
}
```

**Key decisions:**
- Settings scene uses SwiftUI's `.settings { }` modifier (standard macOS pattern)
- Command group replaces `.appSettings` to wire ⌘, to open Settings
- AutoStartManager is stored in @State at app level (singleton)
- Dependencies (ProcessManager, MCPRegistry) passed via environment or constructor injection

---

## 3. Integration Points

### 3.1 App Lifecycle (Quit & Launch)

**On quit (graceful shutdown):**
```
1. App receives NSApplication.willTerminateNotification
   or user selects Quit in menu

2. AppDelegate.applicationWillTerminate() fires

3. Call autoStartManager.saveRunningServers(registry: registry)
   - Enumerate registry.servers
   - Filter for .running state
   - Save names to UserDefaults

4. App quits normally
```

**On launch:**
```
1. ShipyardApp initializes
   - Create AutoStartManager
   - Create ProcessManager, MCPRegistry

2. MCPRegistry.discover() completes
   - Registry populated with available servers
   - All in .idle state (no processes running yet)

3. Call autoStartManager.autoStartSavedServers()
   - Load saved list from UserDefaults
   - Check restoreServersKey setting
   - If OFF, skip (silent)
   - If ON, sequentially start each saved server
   - Handle errors gracefully

4. UI renders with servers in .running state (or .error if failed)
```

**Key decision:** Auto-start happens AFTER discovery completes, not during. This ensures the registry is authoritative before starting.

### 3.2 Settings Persistence

**Storage:** macOS UserDefaults with app-specific domain (bundle ID)

**Keys:**
```
com.inwestomat.shipyard.autoStartRestoreServers   -> Bool (true)
com.inwestomat.shipyard.autoStartDelay             -> Double (2.0)
com.inwestomat.shipyard.autoStartLastRunning       -> [String] (["mac-runner", "lmstudio"])
```

**Scope:** Shared across app restarts, survives Mac reboot (UserDefaults persisted to disk)

**Backup:** User can manually export/import via System Preferences → General → Login Items (macOS 13+) for additional resilience (future work)

### 3.3 UI Integration

**Servers tab (⌘1):**
- Servers starting via auto-start show animated spinner with "Auto-starting..." label
- Auto-start errors show red indicator with tooltip "Failed to auto-start: <reason>"
- User can manually stop a server post-auto-start (next quit saves new state)

**Settings window (⌘,):**
- Settings render in tabbed window (can add more tabs in future)
- Changes apply immediately (no restart needed)
- Toggle OFF then ON again = enable auto-start without side effects

**Logs:**
- Auto-start actions logged with "auto_start" tag: "Starting mac-runner (auto-start 1/3)"
- Failed auto-starts logged: "Failed to auto-start lmstudio: Python 3.10+ not found"

---

## 4. Workflows

### 4.1 First App Launch (No Saved State)

```
1. User downloads Shipyard.app
2. First launch: MCPRegistry discovers 3 servers (all idle)
3. autoStartManager.autoStartSavedServers()
   - UserDefaults[lastRunningServersKey] is empty (or nil)
   - No auto-start action
4. UI shows 3 idle servers, user manually starts them
5. User quits app (⌘Q)
6. autoStartManager.saveRunningServers()
   - Saves 3 running server names to UserDefaults
7. On next launch: auto-start triggers (backward compatible)
```

**Duration:** No delay (no servers to start)

### 4.2 Typical User Workflow (Auto-Start Enabled)

```
Session 1:
1. User launches Shipyard
2. Discovers 3 servers (idle)
3. Manually starts mac-runner and lmstudio (keep another idle)
4. Works for a while...
5. Quits Shipyard (⌘Q)
6. saveRunningServers() saves ["mac-runner", "lmstudio"]

Session 2 (next day, Mac rebooted):
1. User launches Shipyard
2. Discovers 3 servers (idle)
3. autoStartManager.autoStartSavedServers()
   - restoreServersKey = true
   - delay = 2.0 seconds
   - Starts mac-runner (wait 2s)
   - Starts lmstudio (wait 2s)
4. UI shows both running, third idle
5. User continues work (seamless recovery)
```

**Typical duration:** 4-5 seconds (2 servers × 2s delay + startup time)

### 4.3 User Disables Auto-Start

```
1. User opens Preferences (⌘,)
2. Toggle OFF: "Restore previously running servers on launch"
3. Settings saved to UserDefaults
4. Quits Shipyard (with servers running)
5. saveRunningServers() still saves state to UserDefaults
6. On next launch:
   - autoStartManager reads restoreServersKey = false
   - autoStartSavedServers() skips (silent, no error)
   - Servers remain idle
7. User can re-enable toggle at any time
```

**Key decision:** Saved state persists even when toggle is OFF (user can re-enable without losing history)

### 4.4 MCP No Longer in Registry

```
Session 1:
1. User starts mac-runner and lmstudio
2. Quits Shipyard, both saved

Between sessions:
3. Admin deletes _Tools/mcp/lmstudio/manifest.json from disk
4. OR: user manually removes lmstudio via Discovery UI (future feature)

Session 2:
1. Shipyard launches, discovers 2 servers (lmstudio gone)
2. autoStartManager.autoStartSavedServers()
   - Looks up "mac-runner" → found, starts ✓
   - Looks up "lmstudio" → not found, skip
   - Log: "Skipping lmstudio (not found in registry)"
   - Remove "lmstudio" from saved list, save back to UserDefaults
3. Next launch: only mac-runner auto-starts (clean state)
```

**Resilience:** No crashes, no hung processes, saved state cleaned automatically

### 4.5 Failed Auto-Start (Dependency Missing)

```
Session 1:
1. User starts mac-runner (Python 3.10+)
2. Quits, mac-runner saved

Between sessions:
3. User uninstalls Python from system

Session 2:
1. Shipyard launches
2. autoStartManager.autoStartSavedServers()
   - Attempts processManager.start(mac-runner)
   - DependencyChecker fails: "Python 3.10+ not found"
   - processManager sets server.lastError and state to .error
   - autoStartManager logs error but continues
3. UI shows mac-runner with red error indicator
   - Tooltip: "Failed to auto-start: Python 3.10+ not found"
   - Logs visible in Detail view
4. User installs Python or fixes manifest, manually restarts
```

**Key decision:** Failed auto-start doesn't block other starts, error clearly visible in UI

### 4.6 Adjust Auto-Start Delay

```
1. User notices servers starting too fast causes lag
2. Opens Preferences (⌘,)
3. Changes "Auto-start delay" from 2.0s to 3.5s
4. Setting saved immediately to UserDefaults
5. Quits Shipyard
6. Next launch: auto-start uses 3.5s delay between servers
```

**Granularity:** 0.1 second increments (stepper in UI)

### 4.7 Crash Recovery

```
Session 1:
1. User has 3 servers running
2. Shipyard crashes (unhandled exception, etc.)
3. Last saved state was: ["mac-runner", "lmstudio"] (not all 3)

Session 2:
1. User relaunches Shipyard
2. autoStartManager loads last saved state
3. Restarts ["mac-runner", "lmstudio"] (same as before crash)
4. Third server remains idle (wasn't running at crash)
```

**Note:** Crash recovery restores the most recent saved state. If user started a new server after the previous quit but before crash, that state is lost (acceptable trade-off for simplicity).

---

## 5. Error Handling

### 5.1 Auto-Start Errors

| Error | Root Cause | User Sees | Action |
|-------|-----------|-----------|--------|
| Dependency missing | Binary not in PATH | Server shows .error state with tooltip | User installs dependency or fixes manifest |
| Secret not in Keychain | env_secret_keys references non-existent key | Server .error state, error in logs | User stores secret in Keychain |
| Process launch fails | OS error (permission, file not found) | Server .error state, OS error in logs | User fixes manifest or file permissions |
| All saved MCPs fail | Systemic issue (bad manifests, missing deps) | UI shows multiple errors, app still runs | User fixes errors, re-launches |

**Handling:** Each failed start logs error with structured logging (name, reason). Other servers continue to start. UI shows all errors without blocking.

### 5.2 UserDefaults Errors

| Error | Root Cause | User Sees | Action |
|-------|-----------|-----------|--------|
| UserDefaults read fails | Rare: corrupt domain, disk full | Auto-start skipped, error logged | Restart app or clear preferences |
| UserDefaults write fails | Disk full, permission denied | Settings change fails silently, error logged | Free disk space or fix permissions |
| JSON decode error | Corrupted lastRunningServersKey | Auto-start skips, cleans up UserDefaults | App continues normally |

**Handling:** Read errors are non-fatal (skip auto-start). Write errors log but don't crash (user sees in Console.app). JSON errors trigger cleanup (remove corrupted key).

### 5.3 Settings Validation

| Error | Root Cause | User Sees | Action |
|-------|-----------|-----------|--------|
| Delay out of range | User edits UserDefaults manually (1-10 range enforced by UI) | Stepper clamps to valid range | Reset to default (2.0) if corrupted |
| restoreServersKey is not Bool | Rare: manual editing or migration | Treated as false (default OFF) | Log warning, use default |

**Handling:** UI stepper enforces range. Settings loading clamps invalid values to defaults.

---

## 6. Test Coverage

**Scope:** ~25 tests for auto-start functionality

**Categories:**

| Category | Tests | Key scenarios |
|----------|-------|---------------|
| AutoStartManager | ~15 | Save/load state, sequential start, missing MCPs, failed starts, delay handling |
| Settings persistence | ~5 | Load/save settings, UserDefaults integration, invalid values |
| App lifecycle | ~3 | Quit/launch flow, auto-start trigger timing, Settings window opening |
| Integration | ~2 | Full workflow (save on quit → launch → auto-start) |

**Key test scenarios:**

1. **Save running servers on quit:** 3 servers running → saved as ["mac-runner", "lmstudio", "other"]
2. **Load saved servers on launch:** UserDefaults contains saved list → auto-start loads it
3. **Auto-start toggle OFF:** Settings.restoreServers = false → no servers started
4. **Auto-start toggle ON:** Settings.restoreServers = true → all saved servers started
5. **Sequential start with delay:** 3 servers start with 2s delay between each
6. **Missing MCP in registry:** Saved list contains "nonexistent" → skipped, removed from saved list
7. **Failed start:** ProcessManager.start() throws → logged, other servers continue
8. **First launch (no saved state):** UserDefaults empty → no auto-start, no errors
9. **Adjust delay setting:** User changes from 2.0 to 3.5 → next auto-start uses 3.5s delay
10. **Settings window opens:** Press ⌘, → SettingsView renders, user can toggle and change delay

**Testing discipline (per RTK rules):**
- No tests skipped or disabled
- Failing tests treated as spec signals
- All error cases have explicit tests
- Mock ProcessManager and MCPRegistry for unit tests
- Integration tests use real UserDefaults (temporary domain during test)

---

## 7. Configuration and Defaults

### 7.1 Auto-Start Toggle

**Default:** ON (restore servers on launch)
**Stored in:** UserDefaults[autoStartRestoreServersKey]
**Can be changed in:** Preferences window (⌘,)

### 7.2 Auto-Start Delay

**Default:** 2.0 seconds
**Range:** 1.0–10.0 seconds
**Stored in:** UserDefaults[autoStartDelayKey]
**Can be changed in:** Preferences window (⌘,)

### 7.3 Saved Running Servers

**Stored in:** UserDefaults[autoStartLastRunningServersKey]
**Type:** [String] (MCP names)
**Automatically updated:** On app quit (via AutoStartManager.saveRunningServers)
**Manually clearable:** Via Settings window button (future work: "Clear saved servers")

### 7.4 UserDefaults Domain

**Service identifier:** `com.inwestomat.shipyard` (app bundle ID)
**Persistence:** Survives app restart, Mac reboot, macOS updates
**Backup:** Included in Mac Time Machine (automatic)

---

## 8. Security Considerations

### 8.1 Secrets in Auto-Start

**Assumption:** Secrets are still injected from Keychain at process launch (unchanged).

**No secrets in UserDefaults:** Saved list contains only MCP names, not credentials.

**If secret is missing at auto-start:** Process fails to start → error logged + shown in UI (same as manual start).

### 8.2 User Preferences (Settings)

**Storage:** UserDefaults (plaintext, not encrypted)

**Sensitivity:** Toggle and delay are non-sensitive preferences (no security risk)

**Access control:** UserDefaults domain is private to app (standard macOS isolation)

### 8.3 Saved State Integrity

**Attack surface:** User could manually edit UserDefaults to save arbitrary MCP names

**Mitigation:** AutoStartManager filters against MCPRegistry — only MCPs currently in registry can be started

**Result:** Invalid saved names are silently skipped (fail-safe)

---

## 9. Edge Cases and Assumptions

### 9.1 Rapid Start/Stop

**Scenario:** User rapidly starts and stops a server, then quits app.

**Assumption:** Last save wins (saveRunningServers on quit captures final state).

**Result:** If server is stopped at quit time, it won't auto-start on next launch ✓

### 9.2 Multiple Shipyard App Instances

**Scenario:** User somehow runs two Shipyard.app instances (not typical, but possible).

**Assumption:** Each instance has separate process and state, but share UserDefaults.

**Risk:** Both instances write to same UserDefaults keys (race condition).

**Mitigation (future):** Lock file in ~/Library/Caches/com.inwestomat.shipyard/ to ensure single instance.

**For now:** Document as "single instance per machine" assumption.

### 9.3 Manifest Changes During Start

**Scenario:** While auto-start is running servers, user deletes or modifies a manifest.

**Assumption:** MCPRegistry discovery is separate from auto-start (no race).

**Result:** Deleted manifest → auto-start fails gracefully (processed sequentially). Modified manifest → in-memory registry is stale (user must refresh or restart app).

**Future work:** Implement atomic transaction or lock during discovery + auto-start.

### 9.4 UserDefaults Quota

**Scenario:** User has 100+ MCPs (unusual, but theoretically possible).

**Assumption:** UserDefaults can store [String] with 100+ elements (no practical limit).

**Reality:** macOS UserDefaults has no hard quota for this use case. If storage reaches system limit, write will fail (handled as error).

---

## 10. Future Work

### 10.1 Clear Saved State Button (Settings UI)

```swift
Button("Clear Saved Servers") {
    autoStartManager.clearSavedState()
}
.help("Remove all saved servers from auto-start. Does not affect running servers.")
```

### 10.2 Auto-Start Statistics

Show in Settings:
- Last auto-start time
- Number of servers in saved list
- List of saved servers (editable?)

### 10.3 Per-Server Auto-Start Policy

Manifest could specify:
```json
{
  "auto_start": {
    "enabled": true,
    "priority": 1     // start order (0=first, higher=later)
  }
}
```

### 10.4 Crash Recovery Improvements

- Detect crash on launch (leftover lock file)
- Prompt user: "Previous session crashed. Restore servers?" before auto-starting
- Option to skip auto-start if crash detected

### 10.5 Login Item Integration (macOS 13+)

Register Shipyard in System Settings → General → Login Items for automatic launch on Mac startup. Then auto-start would restore servers on reboot.

---

## 11. Manifest Changes (None Required)

Auto-start is configured entirely in Shipyard (Settings UI + UserDefaults). No new manifest fields needed. Existing manifest.json files remain unchanged.

---

## 12. Completeness Checklist

- [x] AutoStartManager — persistence + recovery
- [x] AutoStartSettings model — user preferences
- [x] SettingsView — preferences UI
- [x] ShipyardApp integration — lifecycle hooks, Settings scene
- [x] Error handling — graceful degradation, clear logging
- [x] Edge case handling — missing MCPs, failed starts, crashes
- [x] UserDefaults persistence — keys, storage scope
- [x] Test coverage — ~25 tests
- [x] Security considerations — no secrets in defaults, isolation
- [x] Documentation — this spec

---

## 13. Session and Build History

| Phase | Milestone |
|-------|-----------|
| Session N (this) | Specification written, ready for implementation |
| Session N+1 | AutoStartManager core + tests |
| Session N+2 | Settings UI + app lifecycle integration |
| Session N+3 | Integration testing + edge case fixes |

**Expected completion:** 3–4 sessions (low complexity, well-scoped)

---

## Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-03-25 | 1.0 | Initial specification — ready for implementation |
