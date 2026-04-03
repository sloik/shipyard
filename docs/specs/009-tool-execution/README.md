# Shipyard Tool Execution Queue — Design Specification

## Overview

This folder contains a **complete UX design proposal** for integrating a tool execution queue into Shipyard's Gateway tab. The design enables:

- **Non-blocking execution:** Start a tool, close the form sheet, execution continues in the background
- **Concurrent runs:** Fire off multiple tools at once; they all run in parallel
- **Visible queue:** Bottom panel shows all active/completed executions
- **Inspect responses:** Click a completed execution to see request/response in the detail pane
- **Retry failures:** Re-run a failed tool with one click

**Design Approach:** Persistent bottom panel (macOS native pattern), reuses existing Shipyard patterns (sidebar list + detail pane, @Observable, @MainActor).

---

## Documents

### 1. **EXECUTION_QUEUE_SUMMARY.md** ⭐ START HERE

**Quick overview + implementation roadmap**

- 5-minute read on what the feature does and why
- Quick design overview and layout
- 4-phase implementation plan (data model → UI → integration → polish)
- Checklist of files to create/modify
- Testing strategy and future enhancements

**Read this first if you want the big picture or to assess effort.**

---

### 2. **shipyard-execution-queue-design.md**

**Main specification (12 sections, 500+ lines)**

Deep-dive into the design with complete rationale. Includes:

- **Section 1:** Layout proposal with ASCII mockup
- **Section 2:** Execution queue data model (Swift types)
- **Section 3:** User flow and interaction patterns (3 scenarios)
- **Section 4:** UI components (code snippets for all views)
- **Section 5:** Sheet implementation
- **Section 6:** Integration with GatewayView
- **Section 7:** State diagram (full execution lifecycle)
- **Section 8:** Design decisions and rationale
- **Section 9:** Implementation checklist (Phase 1-4)
- **Section 10:** Code example: starting an execution
- **Section 11:** Accessibility considerations
- **Section 12:** Future extensions

**Read this for detailed specifications, code structure, and rationale.**

---

### 3. **shipyard-execution-architecture.md**

**Technical integration guide (10 sections, 400+ lines)**

Architecture and threading model. Includes:

- **Component dependency graph:** How all pieces fit together
- **Data flow diagram:** Execution lifecycle from click to history
- **SwiftUI Observable pattern:** How state changes trigger UI updates
- **Key patterns from existing Shipyard code:** What to reuse/follow
- **Integration points:** Exact changes needed to GatewayView, ShipyardApp, SocketServer
- **Threading & concurrency notes:** MainActor, Task, non-blocking execution
- **Testing strategy:** Unit tests, integration tests, UI tests
- **Performance considerations:** History limits, lazy rendering, socket load
- **Summary:** Quick reference of all patterns

**Read this for implementation details, threading model, and integration points.**

---

### 4. **shipyard-execution-ui-states.md**

**Visual reference with ASCII mockups (10 states)**

Shows the UI at every stage of the execution flow. Includes:

1. **Idle** — Empty queue, panel collapsed
2. **Tool Execution Form** — Sheet open with parameters
3. **Execution Starting** — Panel auto-expands with new entry
4. **Multiple Executions** — Mixed status icons (⏳✓✗)
5. **Execution Complete** — Details shown in right pane
6. **Retry in Progress** — New execution queued, old failure in history
7. **Error Handling** — Failed execution with error message
8. **Panel Resized** — User dragged divider to make queue taller
9. **Large History** — Scrollable list with 20 entries
10. **Panel Collapsed** — Minimized to title bar only

Also includes:

- **Responsive behavior** for narrow windows
- **Touch/trackpad gestures** for panel resize
- **Keyboard shortcuts** (future enhancement)
- **Accessibility labels** for VoiceOver
- **State transition diagram** showing how user flows between states

**Read this to understand the UI at every stage, or reference for implementation.**

---

## Architecture at a Glance

```
GatewayView (main container)
├── NavigationSplitView
│   ├── Sidebar: Servers/Tools
│   └── Detail: Tools or Execution Details
├── ExecutionQueuePanelView (NEW — bottom)
│   ├── Header: "Execution Queue (2 active, 5 done)"
│   ├── Queue entry rows (ForEach active + history)
│   └── Draggable divider for resize
└── .sheet(ToolExecutionSheet) (NEW)
    └── Parameter form, submits immediately

Data Model:
├── ExecutionQueueManager (@Observable, @MainActor)
│   ├── activeExecutions: [ToolExecution]
│   ├── history: [ToolExecution]
│   ├── func executeToolAsync(tool, request) → ToolExecution
│   └── func retryExecution(execution)
├── ToolExecution (@Observable, @MainActor)
│   ├── status: ExecutionStatus (pending, executing, success, failure)
│   ├── request, response, error
│   └── startedAt, completedAt, elapsedSeconds (computed)
├── ToolExecutionRequest (Codable)
└── ToolExecutionResponse (Codable)
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Bottom panel** | Persistent visibility, doesn't steal tool-list space, follows Terminal/Xcode pattern |
| **Sheet closes immediately** | Non-blocking: user can start another tool without waiting; execution continues in background |
| **Detail pane for responses** | Consistent with existing design (selection → detail); execution entries are "items" like servers |
| **Active + history (no auto-discard)** | Users want to inspect old responses; moving to history keeps active list clean |
| **Status icons (⏳✓✗)** | Immediate visual feedback; accessible via labels |
| **Draggable divider** | Native macOS pattern; familiar to users |
| **Reuse existing patterns** | @Observable, @MainActor, sidebar+detail, environment injection — consistency with Shipyard |

---

## Implementation Phases

### Phase 1: Data Model (2–3 days)

Create `ExecutionQueueManager.swift`, `ToolExecution.swift`, request/response types. Write unit tests.

**Files:**
- `Shipyard/Models/ExecutionQueueManager.swift`
- `Shipyard/Models/ToolExecution.swift`
- `Shipyard/Models/ToolExecutionRequest.swift`
- `Shipyard/Models/ToolExecutionResponse.swift`

### Phase 2: UI Components (2–3 days)

Create panel, rows, sheet, detail views. Build and test visually.

**Files:**
- `Shipyard/Views/ExecutionQueuePanelView.swift`
- `Shipyard/Views/ExecutionQueueRowView.swift`
- `Shipyard/Views/ToolExecutionSheet.swift`
- `Shipyard/Views/ExecutionDetailView.swift`
- `Shipyard/Views/CodeBlockView.swift` (JSON display helper)
- `Shipyard/Views/JSONEditorView.swift` (parameter form helper)

### Phase 3: Integration (1–2 days)

Integrate into `GatewayView.swift`, `ShipyardApp.swift`, and `SocketServer.swift`. Connect all pieces.

**Files (modify):**
- `Shipyard/Views/GatewayView.swift`
- `Shipyard/ShipyardApp.swift`
- `Shipyard/Models/SocketServer.swift`

### Phase 4: Polish (1 day)

Draggable divider, persistence, keyboard shortcuts, accessibility.

---

## Quick Reference: What Changed

### New Types

```swift
enum ExecutionStatus { case pending, executing, success, failure }
struct ToolExecutionRequest: Codable { let toolName: String; let arguments: [String: AnyCodable] }
struct ToolExecutionResponse: Codable { let rawJSON: String; let parsedValue: [String: Any]?; let contentLength: Int }
@Observable @MainActor final class ToolExecution { ... }
@Observable @MainActor final class ExecutionQueueManager { ... }
```

### New Views

```swift
struct ExecutionQueuePanelView { ... }
struct ExecutionQueueRowView { ... }
struct ToolExecutionSheet { ... }
struct ExecutionDetailView { ... }
```

### GatewayView Changes

```swift
// Add environment
@Environment(ExecutionQueueManager.self) private var queueManager

// Add state
@State private var selectedExecution: ToolExecution? = nil
@State private var showExecutionSheet = false
@State private var sheetTool: GatewayTool? = nil

// Modify detailView to check selectedExecution first
// Add play button ▶ to toolRow
// Add ExecutionQueuePanelView at bottom
// Add .sheet(ToolExecutionSheet)
```

### ShipyardApp Changes

```swift
@State private var queueManager = ExecutionQueueManager()
.environment(queueManager)
```

### SocketServer Changes

```swift
@MainActor func callTool(name: String, arguments: [String: AnyCodable]) async throws -> ToolExecutionResponse
```

---

## Testing

**Unit tests** for ExecutionQueueManager lifecycle (create, execute, move to history, clear).

**Integration tests** for sheet open/close, detail pane switching, sidebar navigation.

**UI tests** for draggable divider, collapse/expand, button states.

See `shipyard-execution-architecture.md` Section 9 for detailed test examples.

---

## How to Read This Spec

**If you have 5 minutes:**
→ Read `EXECUTION_QUEUE_SUMMARY.md`

**If you have 15 minutes:**
→ Read Summary + skim Section 1 (Layout) of `shipyard-execution-queue-design.md`

**If you have 30 minutes:**
→ Read Summary + Main Design (Sections 1–6 of design doc)

**If you have 1 hour:**
→ Read all of Summary + Main Design + Architecture

**If you're implementing:**
→ Start with Summary (roadmap), then Main Design (specs), then Architecture (integration details), then UI States (reference while coding)

---

## Key Insights

1. **Non-blocking is key:** Sheet closes immediately; execution continues in background via `Task { await ... }`. This keeps the UI responsive and allows concurrent tool execution.

2. **Bottom panel is best:** A persistent panel at the bottom (like Terminal output, Xcode console) is the most natural place for a queue. Doesn't steal sidebar space, always visible, easily resizable.

3. **Reuse patterns:** ExecutionQueueManager follows the same @Observable/@MainActor pattern as MCPRegistry and GatewayRegistry. ExecutionDetailView reuses the detail pane pattern. Consistency = easier to maintain.

4. **History is important:** Users want to see what ran and inspect responses. Keeping last 20 executions allows inspection without bloating memory.

5. **Status icons work:** ⏳ (running), ✓ (success), ✗ (failed) give instant visual feedback. No parsing needed.

---

## Accessibility

All views include:
- VoiceOver labels for queue entries
- Text alternatives for icons
- Draggable divider (12pt touch target + Shift+↑↓ keyboard alternative)
- Clear button labels
- Focus order and keyboard navigation

See `shipyard-execution-queue-design.md` Section 11 for full accessibility checklist.

---

## Future Extensions

- Export execution log (CSV, JSON)
- Batch execution (queue multiple tools, run in sequence or parallel)
- Scheduled execution (run tool on timer)
- Request templates (save/reuse common parameters)
- Response filtering (search/grep responses)
- Network stats (bytes, latency, response time)
- Execution throttling (limit concurrent runs)

---

## Contact / Questions

This is a complete, production-ready design. All decisions are documented with rationale. If clarification is needed:

1. **What does this component do?** → EXECUTION_QUEUE_SUMMARY.md
2. **How do I build it?** → shipyard-execution-queue-design.md (Sections 4–6, 9)
3. **How does it integrate?** → shipyard-execution-architecture.md (Integration Points)
4. **What does the UI look like?** → shipyard-execution-ui-states.md

---

**Ready to implement.** Start with Phase 1 (data model), then Phase 2 (UI), then Phase 3 (integration), then Phase 4 (polish).
