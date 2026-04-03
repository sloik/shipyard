---
id: BUG-005
priority: 1
layer: 1
type: bugfix
status: done
after: [SPEC-011]
violates: [SPEC-011]
prior_attempts: []
created: 2026-03-26
---

# View Button on Completed Execution Does Nothing

## Problem

In the Execution Queue Panel, clicking the [View] button on a completed execution entry does nothing. The button has a placeholder action comment instead of actual navigation logic. The `ExecutionDetailView` exists as a fully implemented view but is never shown.

**Violated spec:** SPEC-011 (Execution Queue Panel)
**Violated criteria:** AC 6 — Clicking [View] switches the detail pane to show `ExecutionDetailView` with request + response

## Reproduction

1. Open Gateway tab → click ▶ on any tool (e.g., `hear-me-say` → `list_voices`)
2. Execute the tool — it completes and appears in the History section of the queue panel
3. Click the [View] button on the completed entry
4. **Actual:** Nothing happens. No navigation, no detail view, no visual feedback.
5. **Expected:** The Gateway detail pane switches to show `ExecutionDetailView` with the request payload and response JSON.

## Root Cause

`ExecutionQueueRowView.swift` line 39 — the View button action is a no-op placeholder:
```swift
Button(action: { /* Will be implemented with ExecutionDetailView */ }) {
```

`GatewayView.swift` has `@State private var selectedExecution: ToolExecution? = nil` (line 20) but this state is never used anywhere — no conditional in the detail pane checks it, and no callback passes it from the row view.

`ExecutionDetailView.swift` is fully implemented with request/response display, status badge, back button — but nothing instantiates it.

## Requirements

- [ ] R1: Clicking [View] sets the selected execution in GatewayView
- [ ] R2: GatewayView detail pane shows ExecutionDetailView when an execution is selected
- [ ] R3: ExecutionDetailView's "Back to tools" button clears the selection and returns to the tool list
- [ ] R4: The View button works for both success and failure entries

## Acceptance Criteria

- [ ] AC 1: Clicking [View] on a completed execution shows ExecutionDetailView in the detail pane
- [ ] AC 2: ExecutionDetailView shows tool name, status badge, request JSON, and response JSON
- [ ] AC 3: "Back to tools" button returns to the tool catalog view
- [ ] AC 4: AC 6 from SPEC-011 now passes
- [ ] AC 5: Build succeeds with zero errors; all existing tests pass
- [ ] AC 6: No regressions — tool list, sheet, queue panel all still work

## Context

**Key files:**
- `Shipyard/Views/ExecutionQueueRowView.swift` — contains the broken View button (line 39)
- `Shipyard/Views/ExecutionDetailView.swift` — fully implemented, needs to be wired in
- `Shipyard/Views/GatewayView.swift` — has unused `selectedExecution` state (line 20), detail pane needs conditional
- `Shipyard/Views/ExecutionQueuePanelView.swift` — parent of row views

**Wiring approach:**
The row view needs a callback (e.g., `onView: (ToolExecution) -> Void`) that propagates up through the panel to GatewayView, which sets `selectedExecution`. The `detailView` computed property in GatewayView should check `selectedExecution` first, and if set, show `ExecutionDetailView(execution:onBack:)` where `onBack` clears `selectedExecution`.

## Out of Scope

- JSON syntax highlighting improvements (SPEC-012 handles this)
- Keyboard shortcuts for navigation
- Animation transitions between detail views

## Notes for the Agent

- **Read DevKB/swift.md** before coding — especially the @Observable and SwiftUI patterns
- The callback pattern: `ExecutionQueueRowView` needs an `onView` closure → `ExecutionQueuePanelView` passes it through → `GatewayView` provides the implementation that sets `selectedExecution`
- `ExecutionDetailView` already takes `execution: ToolExecution` and `onBack: () -> Void` — match this API
- In GatewayView's `detailView`, add a check for `selectedExecution` BEFORE the existing `isShipyardSelected` / `selectedServer` checks
- **New .swift files are NOT needed** — this is purely wiring existing views
- **Build after every change** — zero errors required
