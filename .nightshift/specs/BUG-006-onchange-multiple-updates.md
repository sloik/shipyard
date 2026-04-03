---
id: BUG-006
priority: 2
layer: 1
type: bugfix
status: done
after: [SPEC-011]
violates: [SPEC-011, NFR-001]
prior_attempts: []
created: 2026-03-26
---

# SwiftUI onChange Fault: "tried to update multiple times per frame"

## Problem

When a tool execution completes, the Xcode console logs a SwiftUI fault:
```
onChange(of: Int) action tried to update multiple times per frame.
Type: Fault | Subsystem: com.apple.SwiftUI | Category: Invalid Configuration
```

This indicates a SwiftUI state update loop where an `onChange` modifier triggers additional state changes in the same frame. While the app doesn't crash, this is a fault-level log from SwiftUI indicating incorrect usage that could cause undefined behavior.

**Violated spec:** SPEC-011 (Execution Queue Panel)
**Violated criteria:** Implicit NFR — the execution queue should not produce SwiftUI faults during normal operation

## Reproduction

1. Open Gateway tab → click ▶ on any tool (e.g., `hear-me-say` → `list_voices`)
2. Click Execute
3. Watch Xcode console as execution completes
4. **Actual:** `onChange(of: Int) action tried to update multiple times per frame` fault appears at the moment the execution succeeds
5. **Expected:** No SwiftUI faults in the console during normal tool execution

## Root Cause

The fault fires at timestamp `22:41:03.626810` — between `callTool: received response` (`.617535`) and `Saved recent call` (`.628666`). This means it's triggered during `ExecutionQueueManager.executeToolAsync()` when the execution transitions from active → success.

Likely culprit: `GatewayView.swift` has `.onChange(of: registry.registeredServers.map(\.state))` which watches an array of server states. When the execution completes and updates `@Observable` state (activeExecutions/history arrays change), SwiftUI may re-evaluate this onChange in the same frame, causing the "multiple updates" fault.

Alternative: The `ExecutionQueuePanelView` header text `"\(activeCount) active, \(completedCount) completed"` recalculates counts from `@Observable` arrays. If the transition from active→history fires two separate array mutations (remove from active + append to history) in rapid succession, the `onChange(of: Int)` on count-derived values could trigger twice per frame.

## Requirements

- [ ] R1: Tool execution completion does not produce SwiftUI faults in the console
- [ ] R2: State transitions (active → history) happen atomically or are batched to avoid multiple-update-per-frame issues
- [ ] R3: The `.onChange` modifiers in GatewayView do not re-trigger during execution state changes

## Acceptance Criteria

- [ ] AC 1: Executing a tool and watching it complete produces zero SwiftUI faults in console
- [ ] AC 2: The `onChange(of: Int) action tried to update multiple times per frame` fault no longer appears
- [ ] AC 3: Executing 3+ tools in rapid succession produces no faults
- [ ] AC 4: Build succeeds with zero errors; all existing tests pass
- [ ] AC 5: No regressions — tool discovery, server state watching, queue panel all still work

## Context

**Key files:**
- `Shipyard/Views/GatewayView.swift` — has `.onChange(of: registry.registeredServers.map(\.state))` (line 40) that watches server state changes for auto-discovery
- `Shipyard/Models/ExecutionQueueManager.swift` — `executeToolAsync()` mutates both `activeExecutions` and `history` arrays
- `Shipyard/Views/ExecutionQueuePanelView.swift` — header reads counts from observable arrays

**Log excerpt:**
```
← [hear-me-say] id=4 response received                    22:41:03.604831
callTool: received response for hear-me-say__list_voices   22:41:03.617535
onChange(of: Int) action tried to update multiple times     22:41:03.626810  ← FAULT
Saved recent call for hear-me-say__list_voices             22:41:03.628666
Execution succeeded: hear-me-say__list_voices              22:41:03.628684
```

**Possible fix approaches:**
1. Batch the active→history transition: remove from active and append to history in a single `withAnimation` or `MainActor.run` block
2. Replace `.onChange(of: registry.registeredServers.map(\.state))` with a more targeted observer that doesn't fire during execution completions
3. Use `Task { @MainActor in }` to defer state updates to the next frame

## Out of Scope

- Other SwiftUI warnings unrelated to execution flow
- Performance optimization of the queue panel
- Rewriting the server state observation pattern (unless that's the root cause)

## Notes for the Agent

- **Read DevKB/swift.md** before coding
- This is a fault, not a warning — SwiftUI considers it an invalid configuration
- The fix should be minimal and targeted — don't restructure the entire observation pattern unless necessary
- Test by running a tool execution and checking Xcode console for SwiftUI faults
- The `.onChange(of: registry.registeredServers.map(\.state))` in GatewayView creates a new array every evaluation — consider if this is the root cause of redundant onChange fires
- **Build after every change** — zero errors required
