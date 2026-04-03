# Shipyard Gateway Tab — Tool Execution Queue Design
**Date:** 2026-03-26 | **Status:** Design Proposal

---

## Executive Summary

This proposal integrates a **persistent execution queue** into the Gateway tab using a **bottom panel** pattern consistent with macOS native apps (Terminal, Xcode). The queue is non-blocking: users can start multiple tool calls, close the execution sheet, and monitor all active/completed executions without UI interference.

**Key Design Decisions:**
1. **Queue location:** Bottom panel (collapsible, persistent)
2. **Queue entry content:** Tool name, status icon, elapsed time, timestamp, action icons
3. **Sheet behavior:** Closes immediately after execution starts; execution continues in queue
4. **Detail pane interaction:** Clicking a queue entry shows its full request/response payload
5. **Patterns:** Reuses existing Shipyard patterns (@Observable, @MainActor, sidebar + detail)

---

## 1. Layout Proposal: Bottom Panel Pattern

### ASCII Mockup

```
┌─────────────────────────────────────────────────────────────────────┐
│ Gateway Tab                                          [Discover ↻]   │
├────────────────────────┬────────────────────────────────────────────┤
│  SIDEBAR               │  DETAIL PANE                               │
│  Gateway              │  (Server tools or Shipyard tools)           │
│  ├─ Shipyard   [✓]   │                                              │
│  ├─ mac-runner [✓]    │  Tool 1: shipyard__gateway_call             │
│  ├─ lmstudio   [✗]    │  Description: Call a tool from a managed MCP
│  └─ hear-me-say       │  [Enable toggle]  [▶ Execute]              │
│                       │                                              │
│  Servers              │  Tool 2: shipyard__logs                      │
│  ├─ lmac-run [✓]      │  ...                                         │
│  └─ ...               │                                              │
│                       │  Tool 3: shipyard__health                    │
│                       │  ...                                         │
│                       │                                              │
│                       │  ──────────────────────────────────────────  │
│                       │  [6 tools] (3 enabled)                       │
├────────────────────────┴────────────────────────────────────────────┤
│ ▼ Execution Queue (3 active, 5 completed)         [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ⏳ shipyard__gateway_call        [1.2s] 14:32:05                   │
│  ✓ shipyard__logs                [0.8s] 14:30:22  [View] [Retry]   │
│  ✗ mac-runner__run_command       [5.4s] 14:28:15  [View] [Retry]   │
│  ⏳ shipyard__health              [0.3s] 14:27:08                   │
│  ✓ shipyard__status              [0.5s] 14:22:41  [View]           │
└────────────────────────────────────────────────────────────────────┘
```

### Panel Behavior

- **Default height:** ~100–120 points (shows ~3–4 queue entries)
- **Draggable divider:** User can resize by dragging the top edge (Divider with drag gesture)
- **Collapse button:** ▼/▶ arrow to collapse/expand the entire panel
- **Auto-expand:** Panel expands automatically when a new execution starts (optional UX; can be manual only)
- **Sticky:** Persists when switching between Shipyard/server detail panes

---

## 2. Execution Queue Data Model

### Queue Entry State Machine

```
                       [User clicks ▶ Execute]
                               ↓
                        PENDING (0–100ms)
                             ↓
                      EXECUTING (async task running)
                        ↙        ↘
                    SUCCESS      FAILURE
                    (elapsed)    (error message)
                        ↓          ↓
                    COMPLETED   FAILED (ephemeral, then moved to history)
```

### Swift Type Definition

```swift
/// Represents a single tool execution in the queue
@Observable @MainActor
final class ToolExecution {
    let id: UUID                    // unique per execution
    let tool: GatewayTool
    let request: ToolExecutionRequest  // payload parameters

    var status: ExecutionStatus = .pending
    var startedAt: Date?
    var completedAt: Date?

    var response: ToolExecutionResponse?  // nil until complete
    var error: String?                    // populated on failure

    // Derived properties
    var elapsedSeconds: Double {
        let end = completedAt ?? Date()
        let start = startedAt ?? Date()
        return max(0.0, end.timeIntervalSince(start))
    }

    var displayStatus: String {
        switch status {
        case .pending: "Starting..."
        case .executing: "Running..."
        case .success: "Success"
        case .failure: "Failed"
        }
    }
}

enum ExecutionStatus {
    case pending, executing, success, failure
}

struct ToolExecutionRequest: Codable {
    let toolName: String
    let arguments: [String: AnyCodable]  // JSON-serializable
}

struct ToolExecutionResponse: Codable {
    let rawJSON: String              // raw response from tool
    let parsedValue: [String: Any]?  // attempt to parse as JSON
    let contentLength: Int
}
```

### Execution Queue Manager

```swift
/// Manages the execution queue and history
@Observable @MainActor
final class ExecutionQueueManager {
    private(set) var activeExecutions: [ToolExecution] = []
    private(set) var history: [ToolExecution] = []  // completed/failed (last 20)

    private var socketServer: SocketServer?  // to invoke tools via Bridge

    /// Start a tool execution (returns immediately, execution continues async)
    func executeToolAsync(_ tool: GatewayTool, request: ToolExecutionRequest) -> ToolExecution {
        let execution = ToolExecution(id: UUID(), tool: tool, request: request)
        activeExecutions.append(execution)

        // Fire off the async task
        Task { await startExecution(execution) }

        return execution
    }

    private func startExecution(_ execution: ToolExecution) async {
        execution.startedAt = Date()
        execution.status = .pending

        defer { execution.completedAt = Date() }

        guard let response = try? await socketServer?.callTool(
            name: execution.tool.prefixedName,
            arguments: execution.request.arguments
        ) else {
            execution.status = .failure
            execution.error = "Socket call failed"
            moveToHistory(execution)
            return
        }

        execution.response = response
        execution.status = .success

        // Auto-move to history after 2 seconds (optional)
        try? await Task.sleep(for: .seconds(2))
        moveToHistory(execution)
    }

    private func moveToHistory(_ execution: ToolExecution) {
        activeExecutions.removeAll { $0.id == execution.id }
        history.insert(execution, at: 0)

        // Keep only last 20 history entries
        if history.count > 20 {
            history.removeLast()
        }
    }

    func clearHistory() {
        history.removeAll()
    }

    func retryExecution(_ execution: ToolExecution) {
        let newExecution = executeToolAsync(execution.tool, request: execution.request)
        // User can watch the retry in the queue
    }
}
```

---

## 3. Flow: User Interaction & Sheet Behavior

### Scenario A: Execute and Close Sheet Immediately

```
User in tool detail pane:
  [Tool name: shipyard__logs]
  [Description: Get logs...]
  [Enable toggle] [▶ Execute]
         ↓
  User clicks ▶ Execute
         ↓
  Action sheet opens: "Execute shipyard__logs"
  - Parameter form (JSON editor or dynamic form)
  - [Cancel] [Execute] buttons
         ↓
  User fills parameters, clicks [Execute]
         ↓
  ToolExecution created, queued in activeExecutions[]
  Sheet dismisses immediately
  Bottom panel auto-expands (or user sees it blinking)
         ↓
  User can:
    - Start another tool in a different pane
    - Collapse the queue to focus on tool list
    - Click queue entry to see request/response in detail

**Sheet timing:** Opens ~100ms, closes ~200ms after user clicks Execute
**Queue update:** Entry appears in ~500ms (pending → executing transition)
**Non-blocking:** User can interact with rest of app while queue runs
```

### Scenario B: User Clicks Completed Queue Entry

```
Queue entry visible in bottom panel:
  ✓ shipyard__logs [0.8s] 14:30:22  [View] [Retry]
         ↓
  User clicks [View] or the entry itself
         ↓
  Detail pane switches to show ExecutionDetailView:
    - Tool name, parameters, timestamp
    - Response body (raw JSON or parsed table)
    - [Copy response] [Retry] [Close] buttons
         ↓
  Detail pane remains in "execution mode" until user:
    - Clicks another server/tool in sidebar
    - Clicks [Close] button
    - Selects another queue entry
```

### Scenario C: User Retries a Failed Execution

```
Queue entry shows failure:
  ✗ mac-runner__run_command [5.4s] 14:28:15  [View] [Retry]
         ↓
  User clicks [Retry]
         ↓
  New ToolExecution spawned with same request
  Failed entry moves to history (or stays in view)
  New entry appears in active section
         ↓
  Queue is now watching two executions (old failure, new attempt)
```

---

## 4. UI Components

### ExecutionQueuePanelView (Bottom Panel Container)

```swift
struct ExecutionQueuePanelView: View {
    @Environment(ExecutionQueueManager.self) private var queueManager
    @State private var isExpanded = true
    @State private var selectedExecution: ToolExecution? = nil

    var body: some View {
        VStack(spacing: 0) {
            // Draggable divider
            VStack {
                RoundedRectangle(cornerRadius: 2.5)
                    .fill(Color.secondary.opacity(0.3))
                    .frame(width: 40, height: 5)
            }
            .frame(height: 12)
            .contentShape(Rectangle())
            .gesture(DragGesture()
                .onChanged { handleResize(delta: $0.translation.height) }
            )

            if isExpanded {
                VStack(spacing: 0) {
                    // Header
                    HStack {
                        HStack(spacing: 4) {
                            Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                                .font(.caption)
                            Text("Execution Queue")
                                .font(.callout)
                                .fontWeight(.medium)

                            let active = queueManager.activeExecutions.count
                            let done = queueManager.history.count
                            Text("(\(active) active, \(done) done)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Button(action: { queueManager.clearHistory() }) {
                            Image(systemName: "trash")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .help("Clear history")
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)

                    Divider()

                    // Queue list
                    ScrollView {
                        VStack(spacing: 0) {
                            // Active executions first
                            ForEach(queueManager.activeExecutions, id: \.id) { execution in
                                ExecutionQueueRowView(
                                    execution: execution,
                                    isSelected: selectedExecution?.id == execution.id,
                                    onSelect: { selectedExecution = execution }
                                )
                                Divider()
                            }

                            // History below
                            ForEach(queueManager.history, id: \.id) { execution in
                                ExecutionQueueRowView(
                                    execution: execution,
                                    isSelected: selectedExecution?.id == execution.id,
                                    onSelect: { selectedExecution = execution }
                                )
                                Divider()
                            }
                        }
                    }
                }
            }
        }
        .background(Color(nsColor: .controlBackgroundColor))
    }

    private func handleResize(delta: CGFloat) {
        // Update panel height via @State or GeometryReader
        // Clamp to min 100pt, max 50% of window
    }
}
```

### ExecutionQueueRowView

```swift
struct ExecutionQueueRowView: View {
    let execution: ToolExecution
    let isSelected: Bool
    let onSelect: () -> Void

    var statusIcon: String {
        switch execution.status {
        case .pending: "hourglass"
        case .executing: "hourglass"
        case .success: "checkmark.circle.fill"
        case .failure: "xmark.circle.fill"
        }
    }

    var statusColor: Color {
        switch execution.status {
        case .pending, .executing: .orange
        case .success: .green
        case .failure: .red
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            // Status icon
            Image(systemName: statusIcon)
                .font(.caption)
                .foregroundStyle(statusColor)
                .frame(width: 16)

            // Tool name and elapsed time
            VStack(alignment: .leading, spacing: 2) {
                Text(execution.tool.originalName)
                    .font(.callout)
                    .fontWeight(.medium)
                    .lineLimit(1)

                HStack(spacing: 8) {
                    Text(String(format: "[%.1fs]", execution.elapsedSeconds))
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    if let startedAt = execution.startedAt {
                        let formatter = DateFormatter()
                        formatter.timeStyle = .short
                        Text(formatter.string(from: startedAt))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Spacer()

            // Action buttons (show only on success/failure)
            if execution.status != .executing && execution.status != .pending {
                HStack(spacing: 4) {
                    Button(action: { /* show response in detail */ }) {
                        Text("View")
                            .font(.caption)
                    }
                    .buttonStyle(.bordered)

                    if execution.status == .failure {
                        Button(action: { /* retry */ }) {
                            Text("Retry")
                                .font(.caption)
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(isSelected ? Color.accentColor.opacity(0.1) : Color.clear)
        .contentShape(Rectangle())
        .onTapGesture(perform: onSelect)
    }
}
```

### ExecutionDetailView (Replaces Detail Pane on Selection)

When user clicks a queue entry, detail pane switches to:

```swift
struct ExecutionDetailView: View {
    @Environment(ExecutionQueueManager.self) private var queueManager
    let execution: ToolExecution
    let onClose: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            // Header
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(execution.tool.originalName)
                        .font(.title3)
                        .fontWeight(.semibold)

                    Text(execution.tool.prefixedName)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fontFamily(.monospaced)
                }

                Spacer()

                Button(action: onClose) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)

            Divider()

            // Request/Response tabs
            TabView {
                // Request tab
                VStack(alignment: .leading, spacing: 8) {
                    Text("Request")
                        .font(.callout)
                        .fontWeight(.semibold)

                    CodeBlockView(json: formatJSON(execution.request.arguments))
                }
                .tabItem {
                    Label("Request", systemImage: "arrow.up.doc")
                }

                // Response tab
                if let response = execution.response {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Response")
                            .font(.callout)
                            .fontWeight(.semibold)

                        CodeBlockView(json: response.rawJSON)
                    }
                    .tabItem {
                        Label("Response", systemImage: "arrow.down.doc")
                    }
                } else if execution.status == .failure {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Error")
                            .font(.callout)
                            .fontWeight(.semibold)

                        Text(execution.error ?? "Unknown error")
                            .font(.body)
                            .foregroundStyle(.red)
                    }
                    .tabItem {
                        Label("Error", systemImage: "exclamationmark.triangle")
                    }
                }
            }
            .padding(.horizontal, 16)

            Divider()

            // Footer actions
            HStack(spacing: 8) {
                Button(action: { UIPasteboard.general.string = execution.response?.rawJSON }) {
                    Label("Copy", systemImage: "doc.on.doc")
                }
                .buttonStyle(.bordered)

                if execution.status == .failure {
                    Button(action: { queueManager.retryExecution(execution) }) {
                        Label("Retry", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                }

                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
        }
    }
}
```

---

## 5. Sheet Implementation (Tool Execution Form)

### ToolExecutionSheet

When user clicks ▶ on a tool row:

```swift
struct ToolExecutionSheet: View {
    @Environment(ExecutionQueueManager.self) private var queueManager
    let tool: GatewayTool
    @State private var parameters: [String: AnyCodable] = [:]
    @State private var isExecuting = false
    @Binding var isPresented: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                // Tool info
                VStack(alignment: .leading, spacing: 4) {
                    Text(tool.originalName)
                        .font(.headline)
                    Text(tool.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
                .background(Color.gray.opacity(0.1))
                .cornerRadius(4)

                // Parameter form (JSON editor or dynamic form)
                JSONEditorView(json: $parameters)

                Spacer()
            }
            .padding(16)
            .navigationTitle("Execute \(tool.originalName)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { isPresented = false }
                }

                ToolbarItem(placement: .confirmationAction) {
                    Button(action: execute) {
                        if isExecuting {
                            ProgressView()
                        } else {
                            Text("Execute")
                        }
                    }
                    .disabled(isExecuting)
                }
            }
        }
    }

    private func execute() {
        let request = ToolExecutionRequest(
            toolName: tool.prefixedName,
            arguments: parameters
        )
        queueManager.executeToolAsync(tool, request: request)
        isPresented = false
    }
}
```

**Sheet behavior:**
- Opens modally (sheet() or similar)
- User fills parameters
- Clicks Execute
- Sheet closes immediately (~100ms)
- Execution begins in background
- User returns to tool list or starts another tool

---

## 6. Integration with GatewayView

### Modified GatewayView Structure

```swift
struct GatewayView: View {
    @Environment(GatewayRegistry.self) private var gatewayRegistry
    @Environment(ExecutionQueueManager.self) private var queueManager  // NEW
    @Environment(ProcessManager.self) private var processManager
    @Environment(MCPRegistry.self) private var registry

    @State private var selectedExecution: ToolExecution? = nil  // NEW
    @State private var showExecutionSheet = false             // NEW
    @State private var sheetTool: GatewayTool? = nil          // NEW

    var body: some View {
        VStack(spacing: 0) {
            NavigationSplitView {
                serverListView
            } detail: {
                detailView
            }

            Divider()

            // NEW: Execution queue panel at bottom
            ExecutionQueuePanelView(selectedExecution: $selectedExecution)
        }
        .sheet(isPresented: $showExecutionSheet) {
            if let tool = sheetTool {
                ToolExecutionSheet(tool: tool, isPresented: $showExecutionSheet)
            }
        }
        // ... other onChange handlers ...
    }

    // Modify toolRow to add play button
    @ViewBuilder
    private func toolRow(tool: GatewayTool, isServerRunning: Bool) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(tool.originalName)
                    .font(.callout)
                    .fontWeight(.medium)

                if !tool.description.isEmpty {
                    Text(tool.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }

            Spacer()

            // NEW: Play button
            Button(action: {
                sheetTool = tool
                showExecutionSheet = true
            }) {
                Image(systemName: "play.fill")
                    .font(.caption)
            }
            .buttonStyle(.plain)
            .help("Execute \(tool.originalName)")
            .disabled(!isServerRunning || !gatewayRegistry.isToolEnabled(tool.prefixedName))

            Toggle("", isOn: .init(
                get: { gatewayRegistry.isToolEnabled(tool.prefixedName) },
                set: { gatewayRegistry.setToolEnabled(tool.prefixedName, enabled: $0) }
            ))
            .toggleStyle(.switch)
            // ... rest of toggle code ...
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    // When user clicks queue entry, show execution detail instead
    @ViewBuilder
    private var detailView: some View {
        if let execution = selectedExecution {
            ExecutionDetailView(
                execution: execution,
                onClose: { selectedExecution = nil }
            )
        } else if isShipyardSelected {
            shipyardCardView
        } else if let selectedServer = selectedServer {
            toolCatalogView(for: selectedServer)
        } else {
            shipyardCardView
        }
    }
}
```

---

## 7. State Diagram

```
┌────────────────────────────────────────────────────────────┐
│ User in GatewayView (tool list visible)                    │
└────────────────────────────────────────────────────────────┘
                           │
                    User clicks ▶
                           │
                 Sheet opens (form)
                           │
              User fills params, clicks Execute
                           │
                    ┌──────┴──────┐
                    │             │
            ToolExecution      Sheet dismisses
            queued in active   (immediately)
                    │             │
                    └──────┬──────┘
                           │
         ExecutionQueuePanelView shows new entry:
              ⏳ tool_name [0.0s] HH:MM:SS
                           │
              ┌────────────┼────────────┐
              │            │            │
         [PENDING]     [EXECUTING]   [TIMEOUT]
              │            │            │
              └─────┬──────┘            │
                    │                  │
                ┌───┴────┐         [FAILED]
                │        │             │
            [SUCCESS] [FAILURE]        │
                │        │             │
                └────┬───┴─────────────┘
                     │
            [Auto-move to history]
                     │
    (Optional: auto-collapse after 2s)
                     │
    User can click to view response,
    retry if failed, or clear history
```

---

## 8. Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| **Bottom panel (not sidebar)** | Persistent, doesn't steal tool-list real estate. Follows Terminal/Xcode pattern. |
| **Sheet closes immediately** | Non-blocking UX: user can start another tool without waiting. Execution continues in background. |
| **Reuse detail pane for responses** | Consistent with existing design: sidebar list → detail pane. Execution entry is treated like a "selection". |
| **Active + history (no auto-discard)** | Users want to see what ran, inspect responses. Moving to history after ~2s keeps active list uncluttered but preserves history for inspection. |
| **Status icons (⏳✓✗)** | Immediate visual feedback. No text needed for quick scanning. |
| **Elapsed time + timestamp** | Helps identify slow/problematic calls. Users can correlate with external events. |
| **Retry button** | Common for API tools: network flakiness, retryable errors. |
| **Clear history button** | Keeps UI from getting bloated after long sessions. |

---

## 9. Implementation Checklist

### Phase 1: Data Model & Manager (Minimal)
- [ ] Add `ToolExecution` class (Observable, MainActor)
- [ ] Add `ExecutionQueueManager` class (Observable, MainActor)
- [ ] Add `ToolExecutionRequest` & `ToolExecutionResponse` structs
- [ ] Wire manager into SocketServer (implement `callTool()`)
- [ ] Write unit tests for queue lifecycle

### Phase 2: UI Components (Bottom Panel)
- [ ] Implement `ExecutionQueuePanelView` (container, divider, header)
- [ ] Implement `ExecutionQueueRowView` (status icon, tool name, elapsed, buttons)
- [ ] Implement `ExecutionDetailView` (tabs for request/response)
- [ ] Implement `ToolExecutionSheet` (form, parameters)
- [ ] Add play button (▶) to existing `toolRow` in GatewayView

### Phase 3: Integration
- [ ] Integrate ExecutionQueueManager into GatewayView
- [ ] Connect sheet open/close to selectedTool state
- [ ] Modify detail pane to show ExecutionDetailView on queue entry selection
- [ ] Add tests for sheet behavior and queue state transitions

### Phase 4: Polish
- [ ] Draggable divider for panel resize
- [ ] Auto-expand on new execution (optional)
- [ ] Persistent panel height (UserDefaults)
- [ ] Keyboard shortcuts: ⌘E to open sheet, ⌘W to close detail
- [ ] Accessibility: VoiceOver labels, focus management

---

## 10. Example Code: Starting an Execution

```swift
// In toolRow(tool:isServerRunning:)
Button(action: {
    sheetTool = tool
    showExecutionSheet = true
}) {
    Image(systemName: "play.fill")
}

// In ToolExecutionSheet after user clicks Execute:
private func execute() {
    let request = ToolExecutionRequest(
        toolName: tool.prefixedName,
        arguments: parameters
    )
    // This call returns immediately; execution continues in background
    let execution = queueManager.executeToolAsync(tool, request: request)
    isPresented = false  // Sheet closes right away
}

// In ExecutionQueueManager:
func executeToolAsync(_ tool: GatewayTool, request: ToolExecutionRequest) -> ToolExecution {
    let execution = ToolExecution(id: UUID(), tool: tool, request: request)
    activeExecutions.append(execution)  // @Observable property triggers UI update

    // Fire off async task (non-blocking)
    Task { await startExecution(execution) }

    return execution
}
```

---

## 11. Accessibility Considerations

- **Queue entries:** Each row should have a clear label: "Shipyard logs tool, executing, started at 2:30 PM"
- **Status icons:** Provide text alternative via `.accessibilityLabel()`
- **Draggable divider:** Make drag target at least 12 points tall, provide keyboard alternative (Shift+↑↓)
- **Sheet:** Title and description should be announced on open
- **Detail view tabs:** Ensure tab navigation is keyboard-accessible (⌘{1,2,3} or ⌘←→)

---

## 12. Future Extensions

1. **Export execution log** — Save request/response to file (CSV, JSON)
2. **Batch execution** — Queue multiple tools at once, see waterfall of results
3. **Scheduled execution** — Run a tool on a timer (e.g., every 5s health check)
4. **Request templates** — Save common parameter sets, reuse them
5. **Response filtering** — Search/grep responses to find specific values
6. **Network stats** — Show bytes sent/received, network latency
7. **Parallel execution limits** — Throttle concurrent executions (max 3 at a time)

---

## Summary

**Execution Queue** integrates into Gateway tab as a **persistent bottom panel** using macOS native patterns (Terminal, Xcode). The design is:

- **Non-blocking:** Sheet closes immediately after Execute clicked; execution continues in queue
- **Visible:** Queue entries always on screen, can be expanded/collapsed
- **Interactive:** Click entry to inspect request/response in detail, retry failed calls
- **Consistent:** Reuses Shipyard patterns (@Observable, @MainActor, sidebar + detail pane)
- **Scalable:** History keeps last 20 entries; UI remains responsive with many active executions

This proposal balances **visibility** (user always knows what's running) with **simplicity** (minimal new UI, familiar patterns).
