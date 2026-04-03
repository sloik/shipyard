# Shipyard Tool Execution Queue — Complete Design Summary

**Date:** 2026-03-26
**Status:** Design Proposal — Ready for Implementation

---

## Quick Overview

A **tool execution queue** allows Shipyard users to:

1. Click ▶ on any tool → fill parameters in a form sheet
2. Submit the form → sheet closes **immediately**
3. Watch the execution run in a **bottom panel** without blocking the UI
4. Start **multiple tools concurrently** — all run together
5. Click on completed executions to view **request/response** in the detail pane
6. Retry failed executions or clear history as needed

**Key Design:** Bottom panel (macOS-native pattern), non-blocking execution, persistent visibility.

---

## Design Documents Provided

| Document | Purpose | Key Content |
|----------|---------|-------------|
| **shipyard-execution-queue-design.md** | Main specification | 12 sections covering layout, data model, UI components, flow, state machine, integration, rationale |
| **shipyard-execution-architecture.md** | Technical integration | Dependency graphs, data flow, Observable pattern, threading model, testing strategy, integration points |
| **shipyard-execution-ui-states.md** | Visual reference | ASCII mockups for 10 UI states, responsive behavior, keyboard shortcuts, accessibility labels |

---

## The Design at a Glance

### Layout

```
┌────────────────────────────────────────────────────────┐
│ GatewayView (main container)                           │
├─────────────────────┬──────────────────────────────────┤
│ Sidebar: Servers    │ Detail: Tools or Executions      │
│  • Shipyard         │ (switches based on selection)    │
│  • mac-runner       │                                  │
│  • lmstudio         │                                  │
├─────────────────────┴──────────────────────────────────┤
│ ▼ Execution Queue Panel (NEW)    [Collapse] [Clear]    │
│  ⏳ shipyard__logs        [2.1s] 14:35:42              │
│  ✓ shipyard__status      [0.5s] 14:34:10  [View]       │
│  ✗ mac-runner__cmd       [3.2s] 14:32:05  [Retry]      │
└────────────────────────────────────────────────────────┘
```

### Execution Flow

```
Tool row ▶ Play button
    ↓
Sheet opens (form)
    ↓
User fills params, clicks Execute
    ↓
ExecutionQueueManager.executeToolAsync(tool, request)
    ↓
ToolExecution created, added to activeExecutions[]
Sheet dismisses immediately
    ↓
Task { await startExecution(execution) } runs in background
    ↓
Socket call to child MCP or Shipyard tool
    ↓
Response received, status = .success / .failure
    ↓
Moved to history, remains visible for inspection
    ↓
User can click [View] to see request/response
User can click [Retry] to run again
```

### State Machine

```
PENDING (< 100ms)
    ↓
EXECUTING (async, socket call running)
    ↓
SUCCESS / FAILURE (response received)
    ↓
MOVED TO HISTORY (after ~2s or immediately)
    ↓
INSPECTABLE (user can view, retry, or delete)
```

---

## Key Features

### 1. Non-Blocking Execution

- Sheet closes in ~100ms
- Execution continues in background via `Task { await ... }`
- User can start multiple tools concurrently
- UI remains responsive

### 2. Visible Queue

- Bottom panel always visible (can be collapsed)
- Shows active executions + history
- Status icons (⏳ running, ✓ success, ✗ failed)
- Elapsed time + timestamp
- Draggable divider to resize panel

### 3. Detail Inspection

- Click queue entry or [View] button
- Detail pane switches to ExecutionDetailView
- Show request parameters (JSON)
- Show response body (raw or parsed JSON)
- Copy response, retry, or return to tool list

### 4. Error Handling

- Failed executions show ✗ icon
- Error message displayed in detail view
- [Retry] button to re-run with same params
- Manual retry doesn't auto-retry; user controls

### 5. History Management

- Last 20 executions kept in memory
- [Clear history] button to discard all
- History persists during session (not cross-session)
- Users can inspect old executions

---

## Implementation Roadmap

### Phase 1: Data Model (2–3 days)

```swift
// Core types
@Observable @MainActor final class ExecutionQueueManager
@Observable @MainActor final class ToolExecution
struct ToolExecutionRequest
struct ToolExecutionResponse
enum ExecutionStatus { case pending, executing, success, failure }

// Mock SocketServer.callTool() for testing
// Write unit tests for queue lifecycle
```

**Files to create:**
- `Shipyard/Models/ExecutionQueueManager.swift`
- `Shipyard/Models/ToolExecution.swift`
- `Shipyard/Models/ToolExecutionRequest.swift`
- `Shipyard/Models/ToolExecutionResponse.swift`

### Phase 2: UI Components (2–3 days)

```swift
// Bottom panel
struct ExecutionQueuePanelView
struct ExecutionQueueRowView

// Sheet
struct ToolExecutionSheet

// Detail view
struct ExecutionDetailView

// Utilities
struct CodeBlockView  // syntax highlight JSON
struct JSONEditorView  // parameter form
```

**Files to create:**
- `Shipyard/Views/ExecutionQueuePanelView.swift`
- `Shipyard/Views/ExecutionQueueRowView.swift`
- `Shipyard/Views/ToolExecutionSheet.swift`
- `Shipyard/Views/ExecutionDetailView.swift`

### Phase 3: Integration (1–2 days)

```swift
// Modify existing files
GatewayView.swift
  + @Environment(ExecutionQueueManager)
  + @State selectedExecution, showExecutionSheet, sheetTool
  + Modified detailView to check selectedExecution first
  + Modified toolRow to add play button ▶
  + Add ExecutionQueuePanelView at bottom
  + Add .sheet(ToolExecutionSheet)

ShipyardApp.swift
  + @State var queueManager = ExecutionQueueManager()
  + .environment(queueManager)

SocketServer.swift
  + func callTool(name: String, arguments: [String: AnyCodable]) -> ToolExecutionResponse
```

### Phase 4: Polish (1 day)

- Draggable divider with resize gesture
- Persist panel height to UserDefaults
- Keyboard shortcuts (⌘E, ⌘W, ↑↓, Delete)
- Accessibility labels and VoiceOver support
- Responsive layout for narrow windows

---

## Data Model Details

### ExecutionQueueManager

```swift
@Observable @MainActor final class ExecutionQueueManager {
    private(set) var activeExecutions: [ToolExecution] = []
    private(set) var history: [ToolExecution] = []

    func executeToolAsync(tool: GatewayTool, request: ToolExecutionRequest) -> ToolExecution
    private func startExecution(_ execution: ToolExecution) async
    private func moveToHistory(_ execution: ToolExecution)
    func clearHistory()
    func retryExecution(_ execution: ToolExecution)
}
```

### ToolExecution

```swift
@Observable @MainActor final class ToolExecution {
    let id: UUID
    let tool: GatewayTool
    let request: ToolExecutionRequest

    var status: ExecutionStatus = .pending
    var startedAt: Date?
    var completedAt: Date?
    var response: ToolExecutionResponse?
    var error: String?

    var elapsedSeconds: Double { computed }
    var displayStatus: String { computed }
}
```

### ToolExecutionRequest / Response

```swift
struct ToolExecutionRequest: Codable {
    let toolName: String
    let arguments: [String: AnyCodable]
}

struct ToolExecutionResponse: Codable {
    let rawJSON: String
    let parsedValue: [String: Any]?
    let contentLength: Int
}
```

---

## UI Component Details

### ExecutionQueuePanelView

- **Header:** Title + active/done counts + [Clear history] button
- **Draggable divider:** 12pt tall, resize cursor, drag gesture
- **List:** ForEach(activeExecutions) + ForEach(history)
- **Each row:** Status icon, tool name, elapsed time, timestamp, [View]/[Retry] buttons
- **Scrollable:** ScrollView for history when > 5 entries
- **Collapsible:** ▼/▶ arrow to expand/collapse panel

### ToolExecutionSheet

- **Modal sheet:** Opens when user clicks ▶ on tool
- **Header:** Tool name + description
- **Form:** JSONEditorView for parameters (or dynamic form)
- **Footer:** [Cancel] [Execute] buttons
- **Behavior:** Closes immediately after Execute clicked

### ExecutionDetailView

- **Header:** Tool name + prefixedName
- **Tabs:** Request | Response | Error
- **Request tab:** Show JSON of parameters
- **Response tab:** Show raw JSON response (or error message)
- **Footer:** [Copy] [Retry] [Close] buttons

---

## Integration with Existing Code

### GatewayView Changes

1. **Add to environment injection:**
   ```swift
   @Environment(ExecutionQueueManager.self) private var queueManager
   ```

2. **Add state variables:**
   ```swift
   @State private var selectedExecution: ToolExecution? = nil
   @State private var showExecutionSheet = false
   @State private var sheetTool: GatewayTool? = nil
   ```

3. **Add sheet modifier:**
   ```swift
   .sheet(isPresented: $showExecutionSheet) {
       if let tool = sheetTool {
           ToolExecutionSheet(tool: tool, isPresented: $showExecutionSheet)
       }
   }
   ```

4. **Modify detailView to check selectedExecution first:**
   ```swift
   if let execution = selectedExecution {
       ExecutionDetailView(execution: execution, onClose: { selectedExecution = nil })
   } else if isShipyardSelected {
       shipyardCardView
   } else if let selectedServer = selectedServer {
       toolCatalogView(for: selectedServer)
   } else {
       shipyardCardView
   }
   ```

5. **Add play button to toolRow:**
   ```swift
   Button(action: { sheetTool = tool; showExecutionSheet = true }) {
       Image(systemName: "play.fill")
   }
   ```

6. **Add bottom panel above closing tag:**
   ```swift
   ExecutionQueuePanelView(selectedExecution: $selectedExecution)
   ```

### ShipyardApp Changes

1. **Add queue manager:**
   ```swift
   @State private var queueManager = ExecutionQueueManager()
   ```

2. **Inject into environment:**
   ```swift
   .environment(queueManager)
   ```

### SocketServer Changes

1. **Add callTool method:**
   ```swift
   @MainActor
   func callTool(
       name: String,
       arguments: [String: AnyCodable]
   ) async throws -> ToolExecutionResponse {
       // Route to child MCP or handle Shipyard tools
   }
   ```

---

## Testing Strategy

### Unit Tests

- `ExecutionQueueManager`: lifecycle tests (create, execute, move to history, clear)
- `ToolExecution`: state transitions, elapsed time calculation
- Mock `SocketServer` for fast testing

### Integration Tests

- Sheet opens/closes on button click
- Detail pane switches to ExecutionDetailView on row selection
- Retry spawns new execution without losing old one
- Queue persists while navigating sidebar

### UI Tests

- Queue panel resize gesture works
- Draggable divider visual feedback
- Collapse/expand button toggles
- Buttons disabled appropriately (e.g., [Retry] only on failed)

---

## Future Enhancements

1. **Export/Log:** Save execution history to file (CSV, JSON)
2. **Batch Mode:** Queue multiple tools at once, run in sequence or parallel
3. **Scheduled:** Run tool on timer (e.g., every 5s health check)
4. **Request Templates:** Save common parameter sets, reuse them
5. **Network Stats:** Show bytes, latency, response time
6. **Throttling:** Limit concurrent executions (max 3 at a time)
7. **Filtering:** Search/grep responses for specific values
8. **Keyboard Nav:** ⌘E, ⌘W, ↑↓, Delete shortcuts

---

## Consistency with Shipyard Patterns

| Pattern | Location | Applied To Queue |
|---------|----------|------------------|
| `@Observable @MainActor` | MCPRegistry, GatewayRegistry | ExecutionQueueManager, ToolExecution |
| Sidebar list + detail pane | GatewayView | Queue entries are "selectable items" |
| Non-blocking Task { } | discoverTools, toggleServer | executeToolAsync doesn't block |
| Sheet modal | (new in this feature) | ToolExecutionSheet |
| Environment injection | @Environment(GatewayRegistry) | @Environment(ExecutionQueueManager) |
| Bottom panel pattern | LogViewer (LogsTab) | Execution queue reuses panel metaphor |
| Error handling | lastError in GatewayView | Execution.error on failure |

---

## Design Decisions Explained

| Decision | Why |
|----------|-----|
| **Bottom panel, not sidebar** | Doesn't steal tool-list space; follows Terminal/Xcode pattern; can be resized/collapsed |
| **Sheet closes immediately** | Non-blocking UX: user can start another tool without waiting; execution continues in background |
| **Detail pane for responses** | Consistent with existing design (sidebar selection → detail); executions are "items" like servers/tools |
| **Active + history (no auto-discard)** | Users want to inspect responses; moving to history after ~2s keeps active list clean but preserves data |
| **Status icons (⏳✓✗)** | Immediate visual feedback; no text parsing needed; accessible via labels |
| **Elapsed time + timestamp** | Help identify slow calls; correlate with external events; useful for debugging |
| **Retry button** | Common for API tools; network flakiness; users control retry (no auto-retry) |
| **Draggable divider** | Native macOS pattern (Xcode, Mail); familiar to users |

---

## Accessibility Checklist

- [ ] VoiceOver labels for each queue row
- [ ] Status icons have text alternatives
- [ ] Draggable divider has 12pt target + text alternative (Shift+↑↓)
- [ ] Sheet title/description announced on open
- [ ] Tab navigation in detail view (⌘{1,2,3})
- [ ] Focus order logical (sidebar → detail → queue → buttons)
- [ ] Color not the only indicator (use icons + text)
- [ ] Button labels clear and descriptive

---

## Performance Notes

- **History limit:** Keep last 20 to avoid memory bloat
- **Lazy rendering:** LazyVStack if history > 50
- **Socket load:** Multiple concurrent executions OK; throttle in future if needed
- **Memory:** Each ToolExecution holds response data; clear old history

---

## Quick Reference: File Additions

**New files to create:**

```
Shipyard/Models/
├── ExecutionQueueManager.swift (100 lines)
├── ToolExecution.swift (80 lines)
├── ToolExecutionRequest.swift (30 lines)
└── ToolExecutionResponse.swift (30 lines)

Shipyard/Views/
├── ExecutionQueuePanelView.swift (150 lines)
├── ExecutionQueueRowView.swift (100 lines)
├── ToolExecutionSheet.swift (120 lines)
├── ExecutionDetailView.swift (150 lines)
├── CodeBlockView.swift (80 lines)  [Utility for JSON display]
└── JSONEditorView.swift (120 lines)  [Form for parameters]
```

**Files to modify:**

```
Shipyard/Views/GatewayView.swift
  - Add @Environment(ExecutionQueueManager)
  - Add @State for selectedExecution, showExecutionSheet, sheetTool
  - Modify detailView conditional
  - Modify toolRow to add ▶ button
  - Add ExecutionQueuePanelView + sheet

Shipyard/ShipyardApp.swift
  - Add @State queueManager
  - Inject into environment

Shipyard/Models/SocketServer.swift
  - Add callTool(name:arguments:) method
```

---

## Summary

This design provides a **complete, production-ready specification** for Shipyard's tool execution queue. It:

1. ✅ Solves the core problem: Non-blocking, concurrent tool execution with visible queue
2. ✅ Follows macOS native patterns (bottom panel, sidebar + detail)
3. ✅ Reuses Shipyard's existing architecture (@Observable, @MainActor, environment injection)
4. ✅ Provides detailed UI specifications (10 states, ASCII mockups, responsive behavior)
5. ✅ Includes implementation roadmap (4 phases, file structure, integration points)
6. ✅ Addresses accessibility, performance, and testing
7. ✅ Extensible for future features (batch mode, scheduling, filtering)

**Ready to implement.** Start with Phase 1 (data model + unit tests), then Phase 2 (UI), then Phase 3 (integration), then Phase 4 (polish).

---

## Document Reference

- **Main Design:** `shipyard-execution-queue-design.md` (12 sections, 500+ lines)
- **Architecture:** `shipyard-execution-architecture.md` (10 sections, 400+ lines)
- **UI States:** `shipyard-execution-ui-states.md` (10 visual states, ASCII mockups)
- **This Summary:** Quick overview and implementation checklist

**All documents use:**
- Consistent terminology (ToolExecution, ExecutionQueueManager, ExecutionStatus)
- ASCII mockups for clarity
- Code examples in Swift
- Rationale for each decision
- Cross-references for coherence
