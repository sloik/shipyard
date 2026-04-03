---
id: SPEC-022
priority: 1
layer: 0
type: refactor
status: done
after: []
prior_attempts: []
nfrs: [NFR-001, NFR-002]
created: 2026-03-30
---

# Remove MenuBarExtra Scene

## Problem

The `MenuBarExtra` scene in ShipyardApp is the #1 source of startup hang symptoms. Trace evidence shows 725+ samples in menu rebuild paths, 386 samples in `MenuBarExtraController.updateButton`, and 241 samples in `NSStatusBarButton.setImage` — all triggered because the menu bar icon's computed properties (`menuBarIconName`, `menuBarIconColor`) read `registry.registeredServers` on every registry change, causing a cascade of SF Symbol resolution and AppKit menu rebuilds on the main thread.

The MenuBarExtra is not essential to Shipyard's core function (MCP orchestration). The main window provides full server management. Removing it eliminates:

1. The dominant startup hang contributor (menu bar scene + computed icon + cross-scene invalidation)
2. The blocked UX-005 spec (no longer needed — its requirements were all menu-bar-specific)
3. A class of SwiftUI/AppKit interop bugs (MenuBarExtra has known rough edges in SwiftUI lifecycle)

## Requirements

- [ ] R1: Remove the `MenuBarExtra` scene entirely from `ShipyardApp.body`
- [ ] R2: Remove `MenuBarView.swift` (the menu bar popover content view)
- [ ] R3: Remove the computed properties `menuBarIconName` and `menuBarIconColor` from `ShipyardApp`
- [ ] R4: Remove any `@AppStorage("menuBar.*")` keys related to menu bar visibility
- [ ] R5: Ensure Shipyard still appears in the Dock as a normal macOS app (it should already — verify `LSUIElement` is NOT set in Info.plist)
- [ ] R6: Ensure the app can still be quit via ⌘Q, the app menu → Quit, or the Dock right-click → Quit
- [ ] R7: If `MenuBarView` references any services/state that other views also reference, ensure no dangling dependencies after removal
- [ ] R8: Remove the `MenuBarExtraController` reference path from any AppDelegate hooks if present
- [ ] R9: Clean up any imports or extensions that only existed for MenuBarExtra support

## Acceptance Criteria

- [ ] AC 1: No menu bar icon appears when Shipyard launches
- [ ] AC 2: `ShipyardApp.body` contains no `MenuBarExtra` scene
- [ ] AC 3: `MenuBarView.swift` is deleted from the project (Xcode project file + disk)
- [ ] AC 4: App launches, shows main window, and all tabs work (Servers, Gateway, Logs, Config, Secrets, Setup, About)
- [ ] AC 5: Starting/stopping MCPs works from the main window Servers tab
- [ ] AC 6: Gateway tool execution works end-to-end
- [ ] AC 7: App quits cleanly via ⌘Q
- [ ] AC 8: Build succeeds with zero errors and zero warnings related to removed code
- [ ] AC 9: No SwiftUI faults in console after launch (NFR-001)
- [ ] AC 10: No crashes (NFR-002)
- [ ] AC 11: Grep the project for "MenuBar" / "menuBar" / "menu_bar" — zero references remain (except in specs/docs)

## Context

### Files to modify/remove:
- **DELETE:** `Shipyard/Views/MenuBarView.swift` — the entire menu bar popover view
- **MODIFY:** `Shipyard/App/ShipyardApp.swift` — remove `MenuBarExtra` scene, remove `menuBarIconName`/`menuBarIconColor` computed properties, remove any `@AppStorage("menuBar.*")` properties
- **MODIFY:** Xcode project file (`Shipyard.xcodeproj/project.pbxproj`) — remove MenuBarView.swift reference
- **CHECK:** `Shipyard/App/AppDelegate.swift` — remove any MenuBarExtra-related hooks if present
- **CHECK:** `Info.plist` — ensure `LSUIElement` is NOT set (app should show in Dock)

### Trace evidence justifying removal:
From UX-005 block reason:
- 725 samples: `AppDelegate.makeMainMenu(updateImmediately:)`
- 542 samples: `AppKitMainMenuItem.updateMainMenu(...)`
- 386 samples: `MenuBarExtraController.updateButton(_:)`
- 241 samples: `NSStatusBarButton.setImage`
- Synchronous `SMAppService.status` call from `MenuBarView.body`

### Related specs affected:
- **UX-005 (Menu Bar Controls):** Becomes **cancelled** — all its requirements were menu-bar-specific
- **UX-001 (Menu Bar Redesign):** Already done; its changes are removed with MenuBarView
- **SPEC-021 (Startup Profiling):** Depends on this spec (`after: [SPEC-022]`). Profiling should measure the post-removal baseline.

## Scenarios

1. User launches Shipyard → main window appears → no menu bar icon → user manages MCPs from the main window as usual → everything works
2. User presses ⌘Q → app quits cleanly → no orphaned menu bar icon remains
3. Developer greps for "MenuBar" in Swift sources → zero hits outside comments/specs → clean removal confirmed

## Out of Scope

- Adding a Dock menu as replacement (future, if needed)
- System tray / background agent mode (different architecture entirely)
- Startup performance fix (SPEC-021 measures; separate spec will fix)

## Notes for the Agent

- **Read `DevKB/swift.md`** and **`DevKB/xcode.md`** before starting
- Use `XcodeRM` to remove `MenuBarView.swift` from the Xcode project (not just disk deletion — must remove from pbxproj)
- After removing the `MenuBarExtra` scene from `ShipyardApp.body`, the app may need `@main` or window lifecycle adjustments if `MenuBarExtra` was providing the "keep alive" behavior. Test that the app doesn't quit when the main window is closed — if it does, add `.handlesExternalEvents(matching: Set(arrayLiteral: "*"))` or similar
- The `ShipyardCommands` scene should remain (keyboard shortcuts)
- The `Settings` scene should remain
- Build after every change — use `mcp__xcode__BuildProject`
- Run the app after the build to verify no menu bar icon appears and the main window is functional
- **Do NOT create new .swift files** — this is a removal spec
