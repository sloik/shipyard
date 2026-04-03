---
id: NFR-002
priority: 0
layer: 0
type: nfr
status: active
created: 2026-03-28
---

# Application Must Not Crash During Normal Operation

## Constraint

The application must produce **zero crashes, fatal errors, or unhandled exceptions** during normal operation. Any crash is a P0 bug regardless of the triggering path.

"Normal operation" includes: launching the app, using keyboard shortcuts (⌘,), opening Settings, navigating all tabs, starting/stopping servers, using the menu bar extra, closing/reopening windows, editing configuration, and all interactive controls.

## Rationale

- **User trust:** A crash destroys user trust instantly. Users may not re-launch the app.
- **Data loss:** In-flight operations (running MCPs, unsaved config edits) are lost on crash.
- **Silent failures:** If Shipyard crashes, all child MCPs lose their orchestrator — Claude loses its tools mid-conversation.

## Scope

This NFR applies to all code paths in the Shipyard app:

- All SwiftUI scenes (WindowGroup, Settings, MenuBarExtra)
- All `@Environment` injection chains — every view that reads an `@Environment` object MUST have that object injected by its parent scene/view
- All keyboard shortcuts and menu commands
- All async tasks and error handling
- All file I/O (config loading, log reading, etc.)

## Common Crash Patterns

| Crash type | Typical cause |
|---|---|
| `No Observable object of type X found` | Missing `.environment(x)` on a scene or sheet |
| `Fatal error: force unwrap of nil` | Unsafe `!` on optional |
| `EXC_BAD_ACCESS` | Use-after-free in async code |
| `Index out of range` | Array access without bounds check |
| `Unhandled error in Task` | Missing do/catch in async task |

## Prevention Rules

1. **Every `@Environment(X.self)` in a view requires a matching `.environment(x)` in the parent scene/sheet/popover.** If a view is used in multiple scenes (e.g., MainWindow + Settings), each scene must inject the dependency.
2. **Force unwraps (`!`) are banned** except in static initialization with known-good data (e.g., decoding a hardcoded JSON string).
3. **All `Task {}` blocks must have do/catch** or the error must be explicitly typed as `Never`.
4. **Sheets and popovers inherit environment from their parent**, but Settings scenes and MenuBarExtra do NOT inherit from WindowGroup — they are separate scenes with separate environment chains.

## Verification

- [ ] V1: Launch app → press ⌘, → Settings opens without crash
- [ ] V2: All keyboard shortcuts in the app menu function without crash
- [ ] V3: Menu bar extra opens, all controls work without crash
- [ ] V4: Close all windows → reopen via Dock icon → no crash
- [ ] V5: For new PRs: verify all `@Environment` usages have matching injections in ALL scenes that host the view

## Known Violations

- BUG-013: Settings window crashes on open — missing `.environment(registry)` in Settings scene

## References

- NFR-001 covers SwiftUI runtime faults (non-fatal). NFR-002 covers fatal crashes.
- Bug specs should use `violates: [NFR-002]` when a crash is the symptom.
