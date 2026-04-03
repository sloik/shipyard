---
id: SPEC-005
priority: 2
layer: 2
type: feature
status: done
after: [SPEC-001, SPEC-002, SPEC-004]
prior_attempts: []
created: 2026-03-25
---

# Shipyard Auto-Start & Remember State

## Problem

Shipyard's Server Management feature (SPEC-001) provides full lifecycle control over MCP servers: start, stop, restart, and real-time monitoring. However, when the app quits (gracefully or via crash) or the Mac reboots, all servers return to idle state. Users must manually restart each one, disrupting workflows.

The **Auto-Start & Remember State** feature persists which servers were running at app shutdown, then automatically restarts them on the next launch. This makes the typical workflow seamless: start lmstudio and mac-runner once, and expect them to remain running across app restarts and reboots.

## Requirements

- [ ] Save the list of running MCP names to UserDefaults on app quit
- [ ] Load saved list from UserDefaults and auto-start all saved MCPs after MCPRegistry discovery completes on app launch
- [ ] Provide Preferences window (accessible via ⌘,) with "Restore servers" toggle and auto-start delay configuration
- [ ] Handle missing MCPs, failed starts, and crash recovery gracefully
- [ ] Use UserDefaults for lightweight persistence (consistent with existing patterns)
- [ ] Implement sequential start with configurable delay to avoid resource spikes
- [ ] Silently remove MCPs no longer in registry (backward compatible)
- [ ] Ensure failures do not block other starts (fail-safe design)
- [ ] Support first launch with no saved state (backward compatible)
- [ ] Integrate Settings UI with macOS standard Preferences shortcut (⌘,)

## Acceptance Criteria

- [ ] AC 1: When app quits with 3 running servers, their names are saved to UserDefaults[autoStartLastRunningServersKey] as [String]
- [ ] AC 2: On app launch after discovery completes, saved servers are sequentially started with configurable delay between each
- [ ] AC 3: Auto-start respects "Restore servers" toggle; when OFF, no servers are started despite saved state
- [ ] AC 4: Auto-start respects "Auto-start delay" setting; servers start with this delay (default 2.0s, range 1.0-10.0s) between each
- [ ] AC 5: If saved server is no longer in registry, it is silently skipped and removed from saved list
- [ ] AC 6: If a server fails to start during auto-start, error is logged but other servers continue
- [ ] AC 7: Failed auto-start shows server in .error state with tooltip explaining reason
- [ ] AC 8: First launch (no saved state in UserDefaults) proceeds without errors or auto-start action
- [ ] AC 9: Preferences window opens via ⌘, and displays toggle and delay stepper with current values
- [ ] AC 10: Settings changes are saved immediately to UserDefaults without requiring restart
- [ ] AC 11: Auto-start logs all actions with structured logging: "Starting <name> (auto-start N/total)" and error reasons
- [ ] AC 12: UserDefaults keys are: autoStartRestoreServersKey (Bool), autoStartDelayKey (Double), autoStartLastRunningServersKey ([String])

## Context

**Key Swift files to reference when implementing:**
- `Shipyard/Services/ProcessManager.swift` — handles server process lifecycle (start/stop), error states, @Observable interface
- `Shipyard/Services/MCPRegistry.swift` — maintains list of available servers, discovery, registry filtering
- `Shipyard/Views/SettingsView.swift` — existing preferences UI structure
- `Shipyard/App/ShipyardApp.swift` — app lifecycle, scene structure, command bindings
- `Shipyard/App/AppDelegate.swift` — app quit hooks (applicationWillTerminate)
- `Shipyard/Models/MCPServer.swift` — MCPServer structure, state enum (.idle, .running, .error), properties

**Design principles:**
- UserDefaults for lightweight persistence (consistent with existing GatewayRegistry patterns)
- Sequential start with configurable delay to avoid resource spikes
- Silent removal of MCPs no longer in registry (backward compatible)
- Failures do not block other starts (fail-safe)
- First launch has no saved state (backward compatible)
- Settings UI integrates with macOS standard Preferences shortcut (⌘,)

**Technical constraints:**
- AutoStartManager must be @MainActor for thread-safe UserDefaults access
- Secrets are still injected from Keychain at process launch (no change)
- Settings persisted to UserDefaults domain: `com.inwestomat.shipyard`
- Auto-start happens AFTER MCPRegistry.discover() completes, not during

## Scenarios

1. **First App Launch (No Saved State)**
   - User downloads Shipyard.app
   - First launch: MCPRegistry discovers 3 servers (all idle)
   - autoStartManager.autoStartSavedServers() checks UserDefaults[lastRunningServersKey] (empty/nil)
   - No auto-start action; UI shows 3 idle servers
   - User manually starts 2 servers, quits app
   - autoStartManager.saveRunningServers() saves 2 names to UserDefaults
   - Next launch: auto-start triggers and restores those 2 servers ✓

2. **Typical User Workflow (Auto-Start Enabled)**
   - Session 1: User launches Shipyard, manually starts mac-runner and lmstudio, works, quits
   - saveRunningServers() saves ["mac-runner", "lmstudio"]
   - Session 2 (next day, Mac rebooted): User launches Shipyard
   - MCPRegistry discovers 3 servers (idle)
   - autoStartSavedServers() runs: restoreServersKey=true, delay=2.0s
   - Starts mac-runner (waits 2s), starts lmstudio (waits 2s)
   - UI shows both running, third idle; user continues work (seamless recovery) ✓

3. **User Disables Auto-Start**
   - User opens Preferences (⌘,)
   - Toggles OFF: "Restore previously running servers on launch"
   - Settings saved to UserDefaults
   - Quits Shipyard (with servers running)
   - saveRunningServers() still saves state to UserDefaults
   - Next launch: autoStartSavedServers() reads restoreServersKey=false, skips (silent, no error)
   - Servers remain idle
   - User can re-enable toggle at any time ✓

4. **MCP No Longer in Registry**
   - Session 1: User starts mac-runner and lmstudio, quits
   - Between sessions: admin deletes lmstudio/manifest.json from disk
   - Session 2: Shipyard launches, discovers 2 servers (lmstudio gone)
   - autoStartSavedServers() looks up "mac-runner" → found, starts ✓
   - Looks up "lmstudio" → not found in registry, skipped
   - Logs: "Skipping lmstudio (not found in registry)"
   - Removes "lmstudio" from saved list, saves back to UserDefaults
   - Next launch: only mac-runner auto-starts (clean state) ✓

5. **Failed Auto-Start (Dependency Missing)**
   - Session 1: User starts mac-runner (Python 3.10+), quits
   - Between sessions: user uninstalls Python from system
   - Session 2: Shipyard launches
   - autoStartSavedServers() attempts processManager.start(mac-runner)
   - DependencyChecker fails: "Python 3.10+ not found"
   - ProcessManager sets server.lastError and state to .error
   - autoStartManager logs error but continues (no block)
   - UI shows mac-runner with red error indicator
   - Tooltip: "Failed to auto-start: Python 3.10+ not found"
   - User installs Python or fixes manifest, manually restarts ✓

6. **Adjust Auto-Start Delay**
   - User notices servers starting too fast causes lag
   - Opens Preferences (⌘,)
   - Changes "Auto-start delay" from 2.0s to 3.5s
   - Setting saved immediately to UserDefaults (no restart needed)
   - Quits Shipyard
   - Next launch: auto-start uses 3.5s delay between servers ✓

7. **Crash Recovery**
   - Session 1: User has 3 servers running
   - Shipyard crashes (unhandled exception)
   - Last saved state was: ["mac-runner", "lmstudio"] (only 2)
   - Session 2: User relaunches Shipyard
   - autoStartManager loads last saved state from UserDefaults
   - Restarts ["mac-runner", "lmstudio"] (same as before crash)
   - Third server remains idle (wasn't running at last save)
   - App continues normally ✓

## Out of Scope

- Advanced auto-start policies (per-server enable/disable) — future spec, requires manifest changes
- Clear Saved State button in Settings — future enhancement
- Auto-start statistics (last run time, count) in Settings — future enhancement
- Per-server auto-start priority (manifest field `auto_start.priority`) — future spec
- Crash detection and user prompt ("Previous session crashed, restore?") — future improvement
- Login Item integration (system-level app auto-launch on Mac startup) — future feature
- Atomic transaction lock during discovery + auto-start — future robustness improvement

## Notes for the Agent

**Implementation order:**
1. Create AutoStartSettings struct (Codable, Equatable)
2. Create AutoStartManager (@MainActor, properties, methods)
3. Implement saveRunningServers() and autoStartSavedServers() core logic
4. Wire app lifecycle: AppDelegate.applicationWillTerminate() → saveRunningServers()
5. Wire app launch: ShipyardApp init → call autoStartSavedServers() after discovery
6. Add SettingsView UI (Toggle + Stepper)
7. Wire ⌘, keyboard shortcut in ShipyardApp (Settings scene)
8. Write ~25 tests covering all scenarios and error cases

**Key implementation details:**
- AutoStartManager.startOne() uses Task { await processManager.start(server) } with configurable delay
- Stepper range 1.0–10.0 enforced by UI; settings loading clamps invalid values to defaults
- UserDefaults keys use static let strings for consistency
- Failed auto-start logs via structured logging: "Failed to auto-start <name>: <reason>"
- Missing MCPs removed from saved list by filtering against registry.servers
- Use @Observable for ProcessManager state changes (UI updates automatically when server state changes)
- Form + Section for SettingsView (standard macOS appearance)
- Settings window uses SwiftUI's `.settings { }` modifier (macOS pattern)

**Testing discipline (per RTK):**
- No tests skipped or disabled
- Failing tests treated as spec signals
- All error cases have explicit tests
- Mock ProcessManager and MCPRegistry for unit tests
- Integration tests use real UserDefaults (temporary domain during test)
- Test data: use fixtures with 2–3 sample MCPs (mac-runner, lmstudio, other)

**Known gotchas:**
- UserDefaults is thread-safe only when accessed from @MainActor. Ensure all reads/writes are @MainActor-scoped.
- Do NOT read UserDefaults in background tasks without dispatching back to main thread.
- Sequential start delay is intentional to avoid resource spikes — do NOT parallelize starts.
- Missing MCPs are silently removed from saved list; this is backward-compatible behavior.
- Crash recovery restores only the most recent saved state. If user started a new server after quit but before crash, that state is lost (acceptable trade-off).

**Build verification:**
- After implementation: `swift build` should succeed
- Run full test suite: `swift test` — expect ~25 tests, all passing
- Manual test: start 2+ servers, quit, relaunch, verify auto-start restores them
- Manual test: toggle ⌘, and verify Preferences window opens and persists changes
