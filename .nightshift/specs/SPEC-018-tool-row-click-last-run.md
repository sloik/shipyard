---
id: SPEC-018
priority: 2
layer: 3
type: feature
status: ready
after: [SPEC-016, SPEC-017]
created: 2026-03-27
---

# Tool Row Click → Last Execution Detail

## Summary

Clicking a tool row in the Gateway tool catalog navigates to the ExecutionDetailView for that tool's most recent execution. If the tool has never been executed, the click does nothing. This gives users a fast path to inspect the last result without scrolling through the execution queue.

## Requirements

- [ ] R1: The entire tool row (except the play button and enable/disable toggle) is a click target that navigates to the last execution detail view.
- [ ] R2: "Last execution" means the most recent `ToolExecution` (from `queueManager.history` or `queueManager.activeExecutions`) whose `toolName` matches `tool.prefixedName`.
- [ ] R3: If no previous execution exists for the tool, the click has no effect — no navigation, no error, no visual feedback.
- [ ] R4: Navigation sets `selectedExecution` to the matched execution, showing the same `ExecutionDetailView` used elsewhere (with Back, Retry, Fast Retry).
- [ ] R5: There is no visual indicator (badge, dot, count) on the tool row for previous runs — the row looks the same as before. Cursor should change on hover to indicate clickability (standard macOS behavior for tappable areas).
- [ ] R6: The play button and toggle must remain independently clickable — they must NOT be swallowed by the row tap gesture.

## Acceptance Criteria

- [ ] AC 1: Clicking a tool row that has at least one past execution navigates to that execution's detail view.
- [ ] AC 2: Clicking a tool row with no past executions does nothing.
- [ ] AC 3: The play button still opens the execution sheet when clicked (not intercepted by row tap).
- [ ] AC 4: The enable/disable toggle still works when clicked (not intercepted by row tap).
- [ ] AC 5: The most recent execution is selected (not an older one).
- [ ] AC 6: Build succeeds with zero errors.
- [ ] AC 7: Existing execution queue behavior (row clicks, Retry, Fast Retry) is unchanged.

## Context

### Key files:
- **`Shipyard/Views/GatewayView.swift`** — `toolRow(tool:isServerRunning:)` method (lines ~359-405) renders each tool row. This is where the tap gesture or `onTapGesture` needs to be added.
- **`Shipyard/Models/ExecutionQueueManager.swift`** — has `history: [ToolExecution]` and `activeExecutions: [ToolExecution]` arrays. The lookup needs to search both (active first, then history) for the latest match by `toolName`.
- **`Shipyard/Views/ExecutionDetailView.swift`** — already supports `onRetry` and `onFastRetry` callbacks, used via `selectedExecution` in GatewayView.

### Tool row structure (GatewayView.swift):
```swift
private func toolRow(tool: GatewayTool, isServerRunning: Bool) -> some View {
    HStack(spacing: 12) {
        VStack { toolName; description }
        Spacer()
        Button(play) { ... }   // must remain independently clickable
        Toggle(enabled) { ... } // must remain independently clickable
    }
}
```

### Execution lookup logic:
Search `queueManager.activeExecutions` + `queueManager.history` for entries where `execution.toolName == tool.prefixedName`, pick the most recent one. Both arrays are ordered with newest entries appended last (or first — agent should verify by reading the code).

### Navigation pattern:
Setting `selectedExecution` in GatewayView already switches the detail pane to `ExecutionDetailView`. The same pattern is used by `ExecutionQueuePanelView.onViewExecution`.

## Out of Scope

- Run history list or count badge on tool rows
- Changing what happens when clicking the play button or toggle
- Any changes to ExecutionDetailView itself

## Notes for the Agent

- **Read DevKB/swift.md** before writing code
- The main challenge is adding a tap gesture to the row WITHOUT swallowing clicks on the play button and toggle. In SwiftUI, this typically requires either: (a) `contentShape` + `onTapGesture` on the text/spacer area only, or (b) wrapping the non-interactive part in a `Button` while keeping the play/toggle separate. **Research the correct SwiftUI pattern before implementing** — a naive `onTapGesture` on the whole HStack will intercept the button/toggle.
- Verify the ordering of `history` and `activeExecutions` arrays to pick the correct "most recent" entry.
- **Build after every change** — use `mcp__xcode__BuildProject`
- **Do NOT create new .swift files**
