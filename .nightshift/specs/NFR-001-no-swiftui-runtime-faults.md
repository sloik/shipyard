---
id: NFR-001
priority: 1
layer: 0
type: nfr
status: active
created: 2026-03-26
---

# No SwiftUI Runtime Faults During Normal Operation

## Constraint

The application must produce **zero SwiftUI fault-level logs** (`Type: Fault | Subsystem: com.apple.SwiftUI`) during normal operation. Any fault indicates incorrect SwiftUI API usage and must be treated as a bug.

"Normal operation" includes: launching the app, navigating all tabs, starting/stopping servers, discovering tools, executing tools, viewing results, resizing panels, and using all interactive controls.

## Rationale

SwiftUI faults are not warnings — they're the framework telling us we're doing something wrong. Consequences:

- **Undefined behavior now:** faults can cause subtle rendering bugs, missed state updates, and layout glitches that are hard to reproduce
- **Breakage later:** Apple may change fault behavior in future macOS releases, turning today's silent fault into tomorrow's crash
- **Signal quality:** a clean console makes real issues visible immediately; a noisy console hides them

## Scope

This NFR applies to all SwiftUI code in the Shipyard app:

- All views (custom and standard)
- All `@Observable` state management
- All `@Environment` injection
- All `.onChange`, `.onAppear`, `.task` modifiers
- All sheet/popover/alert presentations
- All animation and transition code

## Verification

- [ ] V1: Launch app, navigate every tab — zero faults in Console.app filtered to `com.apple.SwiftUI`
- [ ] V2: Execute 3+ tools in sequence — zero faults
- [ ] V3: Start/stop/restart servers — zero faults
- [ ] V4: Resize panels, collapse/expand queue, open/close sheets — zero faults
- [ ] V5: For new PRs: run the modified flows and confirm no new faults

### Common fault patterns to watch for

| Fault message | Typical cause |
|---|---|
| `onChange(of:) action tried to update multiple times per frame` | Cascading state mutations in `.onChange` |
| `Modifying state during view update` | Synchronous state write inside `body` or `init` |
| `Publishing changes from within view updates` | Same as above, via @Observable |
| `Invalid frame dimension (negative or non-finite)` | Bad geometry calculations |
| `Accessing StateObject's object without being installed on a View` | Premature state access |

## Known Violations

- ~~BUG-006: onChange multiple updates per frame~~ — **FIXED** (2026-03-26)

## References

- BUG-006 was the first violation caught by this NFR
- Future bug specs should use `violates: [NFR-001]` when a SwiftUI fault is the symptom
