---
id: BUG-013
priority: 0
layer: 1
type: bug
status: done
violates: [NFR-002]
created: 2026-03-28
---

# Settings Window Crashes on Open — Missing MCPRegistry Environment

## Bug Report

**Reproduction:** Press ⌘, (or use the app menu → Settings) to open the Settings window. The app immediately crashes with a fatal error.

**Crash:** `Fatal error: No Observable object of type MCPRegistry found. A View.environmentObject(_:) for MCPRegistry may be missing as an ancestor of this view.`

**Triggered from:** `SettingsView.body` accessing `@Environment(MCPRegistry.self) var registry` (line 9 of SettingsView.swift).

## Root Cause

In `ShipyardApp.swift`, the `Settings` scene (lines 135-138) only injects `autoStartManager`:

```swift
Settings {
    SettingsView()
        .environment(autoStartManager)
    // MISSING: .environment(registry)
}
```

But `SettingsView` uses `@Environment(MCPRegistry.self) var registry` for:
- Reload Config button (line 143-148: `registry.reloadConfig()`)
- Import from Claude (line 150-160: `registry.reloadConfig()` after import)
- AddMCPSheet (line 111-113: `.environment(registry)`)

The `Settings` scene is a **separate scene** from `WindowGroup` — it does NOT inherit environment objects from `WindowGroup`. Each scene must inject its own environment chain (see NFR-002 prevention rule #4).

## Fix

In `ShipyardApp.swift`, add `.environment(registry)` to the Settings scene:

```swift
Settings {
    SettingsView()
        .environment(autoStartManager)
        .environment(registry)         // ← ADD THIS
}
```

**Also audit** all other scenes for missing environment injections:
- `MenuBarExtra` — currently injects `registry` and `processManager` ✓
- `WindowGroup` — injects registry, processManager, gatewayRegistry, logStore, autoStartManager, executionQueueManager ✓
- `Settings` — only injects autoStartManager ✗ (this bug)

## Acceptance Criteria

- **AC1**: Press ⌘, → Settings window opens without crash
- **AC2**: All Settings functionality works (Reload Config, Import from Claude, Add MCP sheet)
- **AC3**: No other scenes have missing environment injections (audit all scenes in ShipyardApp.body)

## Target Files

- `Shipyard/App/ShipyardApp.swift` — Settings scene environment injection (primary fix)
