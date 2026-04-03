---
id: SPEC-017
priority: 2
layer: 3
type: feature
status: ready
after: [SPEC-015]
created: 2026-03-27
---

# Retry Button in ExecutionDetailView

## Summary

Add "Retry" and "Fast Retry" buttons to the ExecutionDetailView header bar (right side). Retry opens the ToolExecutionSheet pre-filled with the viewed execution's arguments (existing, implemented). Fast Retry immediately re-executes with the same arguments and auto-navigates to the new execution in the detail view.

## Requirements

- [ ] R1: Add an `onRetry` callback to `ExecutionDetailView` — `var onRetry: ((ToolExecution) -> Void)?`
- [ ] R2: Display a "Retry" button at the trailing edge (right side) of the header bar, after the `Spacer()`
- [ ] R3: Button visible for ALL execution statuses (success, failure, cancelled). Hidden for pending/executing.
- [ ] R4: Clicking the button calls `onRetry?(execution)` — the parent (GatewayView) handles opening the sheet pre-filled with arguments, same as the queue row Retry button.
- [ ] R5: Wire up `onRetry` in GatewayView, reusing the existing `onRetryExecution` pattern (find matching GatewayTool → set `sheetInitialArguments` → set `sheetTool`).
- [ ] R6: Add an `onFastRetry` callback to `ExecutionDetailView` — `var onFastRetry: ((ToolExecution) -> Void)?`
- [ ] R7: Display a "Fast Retry" button (`bolt.fill` icon, no label) to the RIGHT of the Retry button. Same visibility rule as Retry (completed statuses only).
- [ ] R8: Clicking Fast Retry calls `onFastRetry?(execution)` — parent calls `queueManager.retryExecution(execution)` and sets `selectedExecution` to the new execution (auto-navigate).
- [ ] R9: Fast Retry button style: `.buttonStyle(.bordered)`, `.font(.callout)`, `.help("Fast retry — re-execute immediately")` — matches queue row pattern.

## Acceptance Criteria

- [ ] AC 1: When viewing any completed execution (success, failure, cancelled), a "Retry" button is visible in the top-right of the header.
- [ ] AC 2: Clicking "Retry" opens the ToolExecutionSheet pre-filled with the same arguments as the viewed execution.
- [ ] AC 3: The button is NOT shown for pending or currently executing items.
- [ ] AC 4: Build succeeds with zero errors.
- [ ] AC 5: Existing Retry/Fast Retry from queue rows still work unchanged.
- [ ] AC 6: A "Fast Retry" button (bolt.fill icon) is visible to the right of the Retry button for completed executions.
- [ ] AC 7: Clicking Fast Retry immediately re-executes and auto-navigates the detail view to the new execution.
- [ ] AC 8: Fast Retry button is NOT shown for pending or executing items.

## Context

### Key files:
- **`Shipyard/Views/ExecutionDetailView.swift`** — Add `onRetry` callback + button in header
- **`Shipyard/Views/GatewayView.swift`** — Wire `onRetry` using existing pattern from `onRetryExecution`

### Current header layout (lines 21-49 of ExecutionDetailView.swift):
```swift
HStack(spacing: 12) {
    Button("Back to tools") { onBack() }  // left
    VStack { toolName; statusBadge + timestamp }
    Spacer()
    // ← NEW: Retry button goes here
}
```

### Existing retry pattern in GatewayView (from SPEC-015):
```swift
// onRetryExecution callback from ExecutionQueuePanelView
ExecutionQueuePanelView(
    onRetryExecution: { execution in
        if let matchingTool = gatewayRegistry.tools.first(where: { $0.prefixedName == execution.toolName }) {
            sheetInitialArguments = execution.request.arguments
            sheetTool = matchingTool
        }
    }
)
```
The same pattern applies here — `ExecutionDetailView.onRetry` should call into the same logic.

### Button styles:
- **Retry**: `.buttonStyle(.bordered)` with `Label("Retry", systemImage: "play.fill")`, `.font(.callout)` — matches "Back to tools" button.
- **Fast Retry**: `.buttonStyle(.bordered)` with `Image(systemName: "bolt.fill")`, `.font(.callout)`, `.help("Fast retry — re-execute immediately")` — matches queue row Fast Retry pattern.

### Fast Retry wiring in GatewayView:
```swift
onFastRetry: { execution in
    let newExecution = queueManager.retryExecution(execution)
    selectedExecution = newExecution  // auto-navigate
}
```

## Out of Scope

- Changing the queue row Retry/Fast Retry behavior

## Notes for the Agent

- **Read DevKB/swift.md** before writing code
- `ExecutionDetailView` currently has `let onBack: () -> Void` — add `onRetry` as an optional callback with default `nil`
- Check ALL call sites of `ExecutionDetailView(execution:onBack:)` — they need to pass the new `onRetry` parameter or rely on the default nil
- The `onRetry` wiring in GatewayView should reuse the EXACT same code as `onRetryExecution` from ExecutionQueuePanelView — extract to a shared method if needed
- **Build after every change** — use `mcp__xcode__BuildProject`
- **Do NOT create new .swift files**
