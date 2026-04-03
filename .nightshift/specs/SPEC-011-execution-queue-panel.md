---
id: SPEC-011
priority: 1
layer: 1
type: feature
status: ready
after: [SPEC-009]
prior_attempts: []
created: 2026-03-26
---

# Execution Queue Panel — Bottom Panel with Active & History Entries

## Problem

After a user executes a tool (via SPEC-010), the execution runs in the background. There is no UI to monitor active executions, view completed results, retry failed calls, or manage execution history. Users need persistent visibility into what's running and what completed.

## Requirements

- [ ] R1: **Bottom panel** in the Gateway tab — persistent, below the sidebar+detail split
- [ ] R2: Panel shows a header: "Execution Queue ({N} active, {M} completed)" with [Collapse ▼/▶] and [Clear history] buttons
- [ ] R3: **Active executions section** — each entry shows: status icon (⏳), tool name (short, without full namespace), elapsed time (live-updating), start timestamp
- [ ] R4: **History section** — completed/failed entries show: status icon (✓ green / ✗ red), tool name, elapsed time (final), timestamp, [View] and [Retry] buttons
- [ ] R5: Clicking [View] on a history entry shows the **full request + response** in the Gateway detail pane (replacing tool list temporarily)
- [ ] R6: Clicking [Retry] creates a new execution with the same payload
- [ ] R7: [Clear history] removes all completed/failed entries (does not affect active executions)
- [ ] R8: Panel is **collapsible** — ▼/▶ toggle hides/shows the queue entries (header stays visible with count)
- [ ] R9: Panel is **resizable** — draggable divider between the main content and the queue panel
- [ ] R10: Panel height persists to UserDefaults across app restarts
- [ ] R11: Active executions show elapsed time updating every second (Timer or TimelineView)
- [ ] R12: When an execution completes, it transitions from active to history with a subtle animation
- [ ] R13: Cancelled executions (via SPEC-009) show as ✗ with "Cancelled" label

## Acceptance Criteria

- [ ] AC 1: Gateway tab has a bottom panel below the NavigationSplitView
- [ ] AC 2: Panel header shows execution counts: "{N} active, {M} completed"
- [ ] AC 3: Active entries show ⏳ icon (SF Symbol: `hourglass`), tool name, live elapsed time, timestamp
- [ ] AC 4: Completed entries show ✓ icon (SF Symbol: `checkmark.circle.fill`, green), tool name, final time, [View] [Retry]
- [ ] AC 5: Failed entries show ✗ icon (SF Symbol: `xmark.circle.fill`, red), tool name, final time, [View] [Retry]
- [ ] AC 6: Clicking [View] switches the detail pane to show `ExecutionDetailView` with request + response
- [ ] AC 7: Clicking [Retry] calls `ExecutionQueueManager.retryExecution()` and a new entry appears in active
- [ ] AC 8: [Clear history] removes all non-active entries
- [ ] AC 9: Collapse toggle hides queue entries, header stays visible with badge count
- [ ] AC 10: Draggable divider resizes the panel (min 60pt, max 300pt)
- [ ] AC 11: Panel height stored in UserDefaults key `execution.queue.panel.height`
- [ ] AC 12: Elapsed time on active executions updates every 1 second
- [ ] AC 13: Entries animate from active → history on completion (opacity/move transition)
- [ ] AC 14: Empty state: panel shows "No executions yet. Click ▶ on a tool to get started."
- [ ] AC 15: Panel works correctly with 0, 1, 5, and 20 entries (no layout overflow)
- [ ] AC 16: Build succeeds with zero errors; all existing tests pass

## Context

**Key Files (read ALL before coding):**

### GatewayView.swift — Host the panel
- The bottom panel sits BELOW the existing NavigationSplitView in a VStack or VSplitView
- The panel reads from `ExecutionQueueManager` via `@Environment`
- Selection state: when user clicks [View], the detail pane switches from tool list to execution detail

### ExecutionQueueManager (from SPEC-009)
- `activeExecutions: [ToolExecution]` — currently running
- `history: [ToolExecution]` — completed/failed (last 20)
- `retryExecution()` — re-run with same payload
- Observe these arrays for UI updates

### MainWindow.swift — Overall window layout
- Check if the Gateway tab content is embedded in MainWindow or standalone
- The bottom panel may need to be at the GatewayView level or MainWindow level

## Implementation Strategy

1. **Create `ExecutionQueuePanelView.swift`** — the bottom panel container
   - VStack: header row (title + counts + buttons) + ScrollView of entries
   - Uses `@Environment(ExecutionQueueManager.self)` to read execution state
   - Collapse state: `@State var isCollapsed = false`
   - Height: `@AppStorage("execution.queue.panel.height") var panelHeight: Double = 120`

2. **Create `ExecutionQueueRowView.swift`** — a single queue entry row
   - Input: `ToolExecution`
   - Renders: status icon + tool name + elapsed time + timestamp + action buttons
   - Live elapsed time: use `TimelineView(.periodic(every: 1))` for active entries

3. **Create `ExecutionDetailView.swift`** — request/response display
   - Shows: tool name, request payload (JSON), response payload (JSON), error message if failed
   - For now, use plain Text views — SPEC-012 will add syntax highlighting
   - Include a "Back to tools" button to return to the tool list

4. **Modify GatewayView.swift:**
   - Wrap existing content in a VStack with the panel at the bottom
   - Add a draggable divider (Divider + DragGesture)
   - Add selection state for switching between tool list and execution detail
   - Add `.sheet` state management if not already done by SPEC-010

## Design Reference

→ See: `docs/specs/009-tool-execution/VISUAL_SUMMARY.txt` — full ASCII layout
→ See: `docs/specs/009-tool-execution/shipyard-execution-ui-states.md` — all 10 states with mockups
→ See: `docs/specs/009-tool-execution/shipyard-execution-architecture.md` § "Component dependencies"

## Out of Scope

- JSON syntax highlighting for request/response (SPEC-012)
- Search within response (SPEC-012)
- Tool execution sheet (SPEC-010)
- Keyboard shortcuts — v2
- Drag-to-reorder queue entries — not needed

## Notes for the Agent

- **TimelineView for live elapsed time** — don't use Timer/onReceive. `TimelineView(.periodic(every: 1))` is the SwiftUI-idiomatic way to update time displays.
- **Draggable divider** — use a `Rectangle().frame(height: 4)` with `.gesture(DragGesture(...))` and `.onChanged { panelHeight = ... }`. Clamp between 60 and 300.
- **@AppStorage for panel height** — persists automatically to UserDefaults
- **Animation** — use `.animation(.default, value: queueManager.activeExecutions.count)` and `withAnimation { }` when moving entries from active to history
- **Panel ordering**: active executions first (newest on top), then a thin separator, then history (newest on top)
- **New .swift files MUST be added via `mcp__xcode__XcodeWrite`**
- **Build after every change** — zero errors required
