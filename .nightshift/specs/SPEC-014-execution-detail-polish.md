---
id: SPEC-014
priority: 1
layer: 3
type: feature
status: done
after: [SPEC-011, SPEC-012, SPEC-013]
prior_attempts: []
created: 2026-03-27
---

# Execution Detail View Polish — Layout, Navigation, and UX Improvements

## Problem

The ExecutionDetailView works but has several UX issues that make it less pleasant to use:

1. **JSON text doesn't wrap lines** — long JSON values (e.g., voice lists) extend off-screen. Users must scroll horizontally to read content.
2. **Request/Response division is fixed** — the horizontal divider between Request and Response sections can't be moved. Users with large responses want more space for the response.
3. **No auto-navigation after Execute** — after clicking Execute and confirming, the user stays on the tool list. They have to manually find the entry in the queue panel and click View.
4. **Request JSON is center-aligned** — the request CodeBlockView content is centered instead of left-aligned. Response is correctly left-aligned.

## Requirements

- [ ] R1: JSON text in CodeBlockView wraps long lines (no horizontal scroll for text content)
- [ ] R2: Request and Response sections separated by a draggable divider
- [ ] R3: Draggable divider has a visual affordance (drag handle / `:::` / grip dots) so users know it's interactive
- [ ] R4: Each section has a minimum height (60pt); double-clicking the divider collapses one section
- [ ] R5: Divider position persists across sessions (UserDefaults)
- [ ] R6: After confirming tool execution, the detail pane auto-navigates to the ExecutionDetailView for that execution
- [ ] R7: Request JSON content is left-aligned (matching Response alignment)
- [ ] R8: Font size reads from the setting defined in SPEC-013

## Acceptance Criteria

- [ ] AC 1: Long JSON values (e.g., 200+ char strings) wrap to the next line instead of extending off-screen
- [ ] AC 2: Line numbers adjust to match wrapped content (or wrap indicators shown)
- [ ] AC 3: A draggable divider separates Request and Response sections
- [ ] AC 4: Divider shows a visual grip/handle (e.g., `⋯` dots or `:::` control) on hover or always
- [ ] AC 5: Dragging the divider resizes Request (top) and Response (bottom) proportionally
- [ ] AC 6: Each section has a minimum height of 60pt — dragging beyond that stops
- [ ] AC 7: Double-clicking the divider collapses the Request section (giving max space to Response); double-clicking again restores
- [ ] AC 8: Divider position persisted to UserDefaults key `execution.detail.dividerPosition`
- [ ] AC 9: After clicking Execute → confirming → sheet dismisses → detail pane automatically shows the ExecutionDetailView for the new execution
- [ ] AC 10: User sees the execution in "Executing" state (⏳) immediately, then transitions to success/failure
- [ ] AC 11: Request CodeBlockView content is left-aligned (no centering)
- [ ] AC 12: Build succeeds with zero errors; all existing tests pass
- [ ] AC 13: No SwiftUI runtime faults (NFR-001)

## Scenarios

1. User executes `list_voices` (large response) → confirms → sheet closes → detail pane shows execution with ⏳ → execution completes → response appears with wrapped JSON → user drags divider up to give more space to response → reads voice list comfortably
2. User executes `shipyard__status` (small response) → double-clicks divider to collapse Request → full view shows Response → double-clicks again → Request restored
3. User quits and reopens Shipyard → divider is at the same position they left it

## Context

**Key files:**
- `Shipyard/Views/ExecutionDetailView.swift` — the view being improved
- `Shipyard/Views/CodeBlockView.swift` — JSON viewer (needs line wrapping)
- `Shipyard/Views/GatewayView.swift` — contains `selectedExecution` state and sheet handling
- `Shipyard/Views/ToolExecutionSheet.swift` — the sheet that triggers execution; needs to communicate the new execution back to GatewayView
- `Shipyard/Models/ExecutionQueueManager.swift` — `executeToolAsync()` returns the `ToolExecution` object

**Implementation approach:**

### Line wrapping (R1, AC 1-2)
In `CodeBlockView`, the current `ScrollView([.horizontal, .vertical])` allows horizontal scrolling. Change to `ScrollView(.vertical)` only, and let Text views wrap. Line numbers become tricky with wrapping — consider removing line numbers for wrapped mode, or showing a line-continuation indicator.

Alternative: Keep line numbers but calculate visual line count based on text wrapping. Simpler: just remove horizontal scroll and let lines wrap naturally — line numbers stay as logical line numbers.

### Draggable divider (R2-R5, AC 3-8)
Replace the static `Divider()` between Request and Response with a draggable resize control:

```
VStack {
    requestSection
        .frame(height: topHeight)

    // Draggable divider
    HStack {
        Spacer()
        Image(systemName: "line.3.horizontal")
            .font(.caption)
            .foregroundStyle(.secondary)
        Spacer()
    }
    .frame(height: 12)
    .contentShape(Rectangle())
    .gesture(DragGesture().onChanged { ... })
    .onTapGesture(count: 2) { toggleCollapse() }

    responseSection
        .frame(maxHeight: .infinity)
}
```

Use `GeometryReader` or calculate based on total available height. Store position as a fraction (0.0-1.0) in `@AppStorage("execution.detail.dividerPosition")` with default 0.35 (35% request, 65% response).

### Auto-navigation (R6, AC 9-10)
The `ToolExecutionSheet` calls `queueManager.executeToolAsync()` which returns a `ToolExecution`. The sheet needs to communicate this execution ID back to `GatewayView` so it can set `selectedExecution`.

Approach: Add a callback `onExecutionStarted: (ToolExecution) -> Void` to `ToolExecutionSheet`. In `GatewayView`, pass this callback when presenting the sheet. When the sheet triggers execution and dismisses, GatewayView sets `selectedExecution = execution`.

### Left-align request (R7, AC 11)
In `ExecutionDetailView.requestPayloadView`, the `CodeBlockView` is inside a `VStack` with padding but no explicit alignment. The issue may be the `.frame(height: 200)` or missing `alignment: .leading`. Add `.frame(maxWidth: .infinity, alignment: .leading)` to the CodeBlockView container.

## Out of Scope

- Syntax highlighting improvements (SPEC-012 covers this)
- Response content type detection (e.g., rendering HTML responses)
- Keyboard shortcuts for divider position
- Copy request/response as curl command
- Side-by-side request/response layout (horizontal split)

## Notes for the Agent

- **Read DevKB/swift.md** before coding
- **Read the current CodeBlockView.swift** — it was recently rewritten (BUG-007) to use per-line SwiftUI Text instead of NSTextView
- The auto-navigation callback pattern: `ToolExecutionSheet` → `onExecutionStarted` callback → `GatewayView` sets `selectedExecution`. The sheet dismisses via `@Environment(\.dismiss)`.
- For the draggable divider, follow the same pattern as `ExecutionQueuePanelView` which already has a working draggable divider
- Double-click to collapse: use `.onTapGesture(count: 2)` — but be careful not to conflict with the single-click drag gesture
- `@AppStorage` key for divider: `execution.detail.dividerPosition` (Double, 0.0-1.0, default 0.35)
- For line wrapping: SwiftUI `Text` wraps by default when given a fixed width. The issue is probably the `ScrollView(.horizontal)` preventing wrapping. Remove horizontal scroll.
- **Build after every change** — zero errors required
- This is a Layer 3 (polish) spec — focus on UX quality
