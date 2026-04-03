---
id: UX-005
priority: 2
layer: 3
type: feature
status: done
after: [UX-001, BUG-013]
created: 2026-03-28
---

# Menu Bar Extra — Quit, Settings Toggle, and Launch Control

## Problem

The menu bar extra (MenuBarView) is missing essential macOS app controls:

1. **No way to quit Shipyard** from the menu bar. The only way to quit is via ⌘Q when the main window is focused, or Force Quit. Menu bar apps that run without a Dock icon are especially dependent on having a Quit option in the menu bar.
2. **No way to control whether the menu bar icon is shown.** Users who don't want a menu bar icon have no setting to hide it.
3. **Unclear how Shipyard was started.** The menu bar icon appears but it's unclear if the app was launched at login or manually. Users need visibility into this.

## Requirements

### R1: "Quit Shipyard" menu item

Add a **"Quit Shipyard"** button at the bottom of MenuBarView, below the existing control buttons and separated by a Divider.

- Label: "Quit Shipyard" with `systemImage: "power"`
- Action: `NSApplication.shared.terminate(nil)`
- Style: `.plain`, red foreground color for visibility
- Position: very last item in the popover

### R2: "Settings…" menu item

Add a **"Settings…"** button in the control buttons area (bottom of MenuBarView), next to "Open Shipyard".

- Label: Settings gear icon (`systemImage: "gearshape"`)
- Action: Opens the Settings window — uses `NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)` or the SwiftUI `SettingsLink` approach
- This depends on BUG-013 being fixed first (Settings currently crashes)

### R3: Settings toggle for menu bar visibility

Add a new section in `SettingsView` called **"Menu Bar"** with:

- Toggle: **"Show in menu bar"** — controls whether the MenuBarExtra is visible
- Backed by `@AppStorage("menuBar.showIcon")` with default `true`
- In `ShipyardApp.swift`, the `MenuBarExtra(isInserted:)` binding should read from this AppStorage value instead of `.constant(true)`

Implementation note: `MenuBarExtra(isInserted:)` takes a `Binding<Bool>`. Currently it's `.constant(true)`. Change to `$showMenuBarIcon` backed by `@AppStorage("menuBar.showIcon") private var showMenuBarIcon = true`.

### R4: Launch at Login indicator in menu bar

Add a subtle indicator in the menu bar control area showing the app's launch-at-login status:

- If launch-at-login is enabled: show a small caption text "Launches at login" below the control buttons
- If not: show nothing (don't nag)
- Read from `SMAppService.mainApp.status == .enabled`
- This is informational only — the toggle to control it stays in MainWindow's toolbar

## Acceptance Criteria

- **AC1**: "Quit Shipyard" button visible at the bottom of menu bar popover, clicking it quits the app
- **AC2**: "Settings" button visible in control area, clicking it opens Settings window (requires BUG-013 fix)
- **AC3**: `@AppStorage("menuBar.showIcon")` toggle in Settings controls menu bar visibility
- **AC4**: Setting the toggle to OFF hides the menu bar icon; ON shows it
- **AC5**: Launch-at-login status shown as informational text when enabled
- **AC6**: All existing menu bar functionality (server list, start/stop, open main window) unchanged

## Target Files

- `Shipyard/Views/MenuBarView.swift` — add Quit, Settings, launch-at-login indicator
- `Shipyard/Views/SettingsView.swift` — add "Menu Bar" settings section
- `Shipyard/App/ShipyardApp.swift` — change `MenuBarExtra(isInserted:)` from `.constant(true)` to AppStorage binding

## Notes

- `MenuBarExtra(isInserted:)` with a dynamic binding is the standard SwiftUI API for show/hide — no AppKit hacks needed
- `NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)` is the reliable way to open Settings from non-SettingsLink contexts (like a Button in MenuBarExtra)
- The Quit button should use `.foregroundStyle(.red)` to match macOS convention for destructive actions in menus
