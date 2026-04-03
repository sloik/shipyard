---
id: BUG-015
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [SPEC-005]
prior_attempts: []
created: 2026-03-31
---

# AutoStart: Running Server State Never Saved on Quit

## Problem

`AutoStartManager.saveRunningServers()` is never called in production code. The restore path (`loadSavedServers()` → `autoStartServers()`) works correctly and is wired in `ShipyardApp.swift`, but the save path has no lifecycle hook. `AppDelegate` only implements `applicationDidFinishLaunching` — there is no `applicationWillTerminate` or equivalent. As a result, `UserDefaults` never gets the running server list written, so on every launch `loadSavedServers()` returns empty and nothing auto-starts.

The tests pass because they call `saveRunningServers()` directly — they test the save/restore mechanism in isolation, not the actual lifecycle trigger.

## Reproduction

1. Start one or more MCP servers in Shipyard
2. Quit the app (⌘Q or Stop in Xcode)
3. Re-launch
4. No servers start → bug confirmed

## Fix

Observe `NSApplication.willTerminateNotification` in `ShipyardApp.swift` (where both `registry` and `autoStartManager` are in scope) and call `saveRunningServers` there:

```swift
// In ShipyardApp body, on the WindowGroup or Settings scene:
.onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
    let running = registry.registeredServers.filter { $0.state.isRunning }
    autoStartManager.saveRunningServers(running)
}
```

This is preferred over adding logic to `AppDelegate` because `AppDelegate` has no access to `registry` or `autoStartManager` — they're owned by `ShipyardApp`'s `@State`.

**Do NOT use `scenePhase` changes (`.background`/`.inactive`) for this.** On macOS, `scenePhase` transitions fire frequently during normal use (e.g., when the window loses focus) and would incorrectly overwrite the saved state while servers are still running.

## Acceptance Criteria

- [ ] AC 1: Starting one or more servers, then quitting and relaunching Shipyard causes those servers to auto-start on the next launch
- [ ] AC 2: Starting servers, stopping them, then quitting and relaunching does NOT auto-start them (stopped servers are not saved)
- [ ] AC 3: `UserDefaults` key `autoStartLastRunning` contains valid data after a normal quit
- [ ] AC 4: The fix does not interfere with `scenePhase` or cause premature saves on window focus changes
- [ ] AC 5: Build succeeds with zero errors; existing tests pass

## Files

- `Shipyard/App/ShipyardApp.swift` — add `.onReceive(NSApplication.willTerminateNotification)` modifier
- `Shipyard/App/AppDelegate.swift` — no changes needed
