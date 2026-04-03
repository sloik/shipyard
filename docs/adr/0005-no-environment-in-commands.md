# ADR 0005: @Environment Forbidden in SwiftUI Commands Structs

**Status**: Accepted

**Date**: 2026-03-15 (Session 56)

**Deciders**: project maintainer, AI assistant

---

## Context

Shipyard's `ShipyardCommands` struct (a `Commands` conformer) used `@Environment(MCPRegistry.self)`, `@Environment(ProcessManager.self)`, and `@Environment(LogStore.self)` to access Observable objects. This pattern caused a fatal crash at launch:

```
applicationWillFinishLaunching
→ CommandMenu.MakeList.commandMenu.getter
→ "No Observable object of type MCPRegistry found."
```

**Root cause**: `Commands` structs live at the Scene level, outside the SwiftUI view hierarchy. The `.environment()` modifiers applied to views inside `WindowGroup` never propagate to the `.commands {}` block. All three `@Environment` lookups returned `nil` at launch, triggering the crash.

This is a fundamental architectural mismatch: the environment binding system assumes the property is accessed within the view tree, but `Commands` blocks execute before—and independently of—view initialization.

## Decision

Never use `@Environment` in `Commands` structs. Pass `@Observable` objects as `let` stored properties via the initializer instead.

**Pattern**:
```swift
struct ShipyardCommands: Commands {
    let registry: MCPRegistry
    let processManager: ProcessManager
    let logStore: LogStore

    var body: some Commands {
        CommandMenu("…") { … }
    }
}
```

And in `ShipyardApp`:
```swift
CommandGroup(replacing: .appMenu) {
    ShipyardCommands(
        registry: registry,
        processManager: processManager,
        logStore: logStore
    )
}
```

## Rationale

1. **`@Observable` types are reference types**: Passing them as `let` properties preserves the reference and observation chain. Mutations on the objects propagate correctly to all holders of the reference.

2. **View and Command access the same instance**: Both the commands and views receive the identical object instance, ensuring consistent state.

3. **Apple's documented pattern**: This is the standard way to share state with commands when the state is already managed by the View or App struct.

4. **Avoids environment inheritance assumptions**: By not relying on the environment binding system, we eliminate the coupling between where objects are placed in the hierarchy and where commands are defined.

## Consequences

### Positive

- ✓ Crash eliminated entirely; no more runtime lookup failures
- ✓ State propagation is explicit and type-safe at compile time
- ✓ Regression test suite added:
  - Test 1: Verify both Commands and views receive the same instance (reference identity via `===`)
  - Test 2: Verify mutations propagate (change property on instance passed to Commands, confirm view sees change)
  - Test 3: Mirror-based inspection to confirm no stale `@Environment` properties remain
- ✓ Pattern documented in DevKB entry 34

### Negative

- ✗ Slightly more verbose call site in `ShipyardApp` (three explicit parameters instead of implicit environment lookup)
- ✗ Requires discipline: new `Commands` structs must remember to accept objects as initializer parameters

## Alternatives Considered

1. **`@FocusedObject`**: Only works when a window has focus. At app launch (before any window is focused), lookups still fail. Not a viable solution.

2. **Module-level singletons or global variables**: Eliminates dependency injection, violates testability, makes mocking difficult. Not acceptable.

3. **`@EnvironmentObject` (ObservableObject pattern)**: Same problem as `@Environment`. The `Commands` struct still sits outside the view hierarchy; environment modifiers from view trees do not propagate.

4. **Pass-through via intermediate view**: Create a dummy view that holds `@Environment` and passes values to Commands via bindings. Overcomplicated and adds unnecessary view layers.

## Related ADRs

- **ADR 0001** — Native Swift first: This decision reinforces the preference for native SwiftUI patterns over workarounds.
- **ADR 0004** — Logging with LogStore: `LogStore` is one of the three Observable objects affected by this issue; this ADR ensures LogStore is used correctly in commands.

## Revision History

- **2026-03-15**: Initial acceptance. Three test cases written. Pattern documented in DevKB.
