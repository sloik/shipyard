---
id: BUG-016
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [SPEC-005]
prior_attempts: [BUG-015]
created: 2026-03-31
---

# AutoStart: Save Running State Incrementally, Not On Quit

## Problem

BUG-015 wired `saveRunningServers` to `NSApplication.willTerminateNotification`, which only fires on graceful quit (⌘Q). It does not fire when:

- **Xcode stops the app** (⌘. or Stop button) — Xcode sends `SIGKILL`, which kills the process instantly. No cleanup code runs.
- **The app crashes** — process dies; no notifications fire.
- **System shutdown** — OS may SIGKILL before the notification is delivered.

Result: every Xcode test run starts with an empty `autoStartLastRunning` key in UserDefaults — nothing ever auto-starts.

## Root Cause

Saving on quit is the wrong model. The correct model is: **write the running server list to UserDefaults every time a server's state changes to `.running` or `.idle`**. This way the persisted state is always current regardless of how the app ends.

## Fix

### 1. Inject `AutoStartManager` into `ProcessManager`

`ProcessManager` already accepts `registry: MCPRegistry?` as a weak var. Add the same pattern for `autoStartManager`:

```swift
// In ProcessManager:
weak var autoStartManager: AutoStartManager?
```

Wire it in `ShipyardApp.swift` alongside the existing injection:
```swift
processManager.autoStartManager = autoStartManager
```

### 2. Save after every state transition in ProcessManager

After each point where `server.state` is set to `.running` or `.idle`, call save:

```swift
// Helper — call this after any state change
private func persistRunningState() {
    guard let registry, let autoStartManager else { return }
    let running = registry.registeredServers.filter { $0.state.isRunning }
    autoStartManager.saveRunningServers(running)
}
```

Call `persistRunningState()` immediately after:
- `server.state = .running` (stdio start success, line ~208)
- `server.state = .running` (HTTP connect success, line ~631)
- `server.state = .idle` (stop — graceful exit, line ~309)
- `server.state = .idle` (stop — SIGKILL fallback, line ~336)
- `server.state = .idle` (stop — no process found, line ~293)
- `server.state = .idle` (HTTP disconnect, line ~663)

Do NOT call on `server.state = .error(...)` — an errored server was not successfully running and should not be restored.

### 3. Remove the willTerminateNotification approach from BUG-015

Remove the `.onReceive(NSApplication.willTerminateNotification)` modifier added by BUG-015 from `ShipyardApp.swift`. It is now redundant and misleading.

Optionally keep it as a belt-and-suspenders for normal quits — but it must not be the primary mechanism.

## Why Not `.onChange` in SwiftUI?

An alternative is to observe `registry.registeredServers` state changes in `ShipyardApp` via `.onChange(of:)`. This is problematic because:
- It relies on SwiftUI's render cycle to pick up nested `@Observable` property changes — timing is not guaranteed to be synchronous with the state transition.
- It adds complexity to `ShipyardApp` which is already large.
- `ProcessManager` calling save directly is explicit and testable.

## Acceptance Criteria

- [ ] AC 1: Start a server in Xcode, then click Stop (⌘.) — on next Xcode run, that server auto-starts
- [ ] AC 2: Start a server, then stop it via the UI — on next launch, it does NOT auto-start
- [ ] AC 3: Start two servers, stop one — on next launch, only the still-running one auto-starts
- [ ] AC 4: `UserDefaults.standard.data(forKey: "autoStartLastRunning")` is non-nil immediately after a server reaches `.running` state
- [ ] AC 5: The `willTerminateNotification` observer from BUG-015 is removed from `ShipyardApp.swift`
- [ ] AC 6: Build succeeds with zero errors; existing tests pass

## Files

- `Shipyard/Services/ProcessManager.swift` — add `weak var autoStartManager`, add `persistRunningState()` helper, call it after each state transition
- `Shipyard/App/ShipyardApp.swift` — inject `autoStartManager` into `processManager`; remove `willTerminateNotification` observer

## Verify

After the fix, inspect UserDefaults directly to confirm the key is being written:

```bash
defaults read com.shipyard.app autoStartLastRunning
```

This should return a non-empty value immediately after a server starts, without quitting the app.
