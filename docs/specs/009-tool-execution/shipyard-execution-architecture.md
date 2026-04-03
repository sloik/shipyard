# Shipyard Execution Queue — Architecture & Integration

## Component Dependency Graph

```
GatewayView (main view container)
├── NavigationSplitView
│   ├── serverListView (sidebar)
│   │   └── toolRow(tool:)
│   │       └── Button ▶ → opens ToolExecutionSheet
│   │
│   └── detailView (right pane)
│       ├── When tool selected: toolCatalogView
│       └── When execution selected: ExecutionDetailView (NEW)
│
├── ExecutionQueuePanelView (NEW — bottom)
│   ├── Header: "Execution Queue (3 active, 5 done)"
│   ├── ExecutionQueueRowView (for each active)
│   └── ExecutionQueueRowView (for each history)
│
└── .sheet(ToolExecutionSheet)
    └── Dismisses immediately after Execute clicked
```

## Data Flow: Execution Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│ GatewayView                                                          │
│                                                                      │
│  @Environment(ExecutionQueueManager.self) var queueManager         │
│  @State var selectedExecution: ToolExecution? = nil                │
│  @State var sheetTool: GatewayTool? = nil                          │
│  @State var showExecutionSheet: Bool = false                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
             │
             │ (user clicks ▶)
             ↓
┌─────────────────────────────────────────────────────────────────────┐
│ ToolExecutionSheet                                                   │
│                                                                      │
│  let tool: GatewayTool                                              │
│  @State var parameters: [String: AnyCodable] = [:]                 │
│                                                                      │
│  User fills params, clicks Execute                                  │
│  → queueManager.executeToolAsync(tool, request: parameters)         │
│  → Sheet dismisses immediately                                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────────────────────────────────┐
│ ExecutionQueueManager (MainActor, Observable)                       │
│                                                                      │
│  func executeToolAsync(tool: GatewayTool, request: TER) -> TE {    │
│    1. Create ToolExecution(id, tool, request)                       │
│    2. Append to activeExecutions                                    │
│    3. Task { await startExecution(execution) } → non-blocking       │
│    4. Return immediately                                             │
│  }                                                                   │
│                                                                      │
│  private func startExecution(execution: ToolExecution) {            │
│    1. execution.status = .pending                                   │
│    2. execution.startedAt = Date()                                  │
│    3. response = await socketServer?.callTool(...)                  │
│    4. execution.status = .success / .failure                        │
│    5. execution.completedAt = Date()                                │
│    6. moveToHistory(execution)                                      │
│  }                                                                   │
│                                                                      │
│  @ObservedReactionEffect on activeExecutions/history changes        │
│  → ExecutionQueuePanelView observes and re-renders                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────────────────────────────────┐
│ ExecutionQueuePanelView (observes queueManager)                     │
│                                                                      │
│  @Environment(ExecutionQueueManager) var queueManager               │
│  @State var selectedExecution: ToolExecution?                       │
│                                                                      │
│  ForEach(queueManager.activeExecutions) { execution in              │
│    ExecutionQueueRowView(execution: execution, onSelect: {...})     │
│  }                                                                   │
│  ForEach(queueManager.history) { execution in                       │
│    ExecutionQueueRowView(execution: execution, onSelect: {...})     │
│  }                                                                   │
│                                                                      │
│  When row tapped: selectedExecution = execution                     │
│  → Triggers GatewayView.detailView to show ExecutionDetailView     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
             │
             ↓ (user clicks [View] on row)
             │
┌─────────────────────────────────────────────────────────────────────┐
│ GatewayView.detailView (conditional)                                │
│                                                                      │
│  if let execution = selectedExecution {                             │
│    ExecutionDetailView(execution: execution, onClose: {...})        │
│  } else if isShipyardSelected {                                     │
│    shipyardCardView                                                 │
│  } else if selectedServer != nil {                                  │
│    toolCatalogView(for: selectedServer)                             │
│  }                                                                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
             │
             ↓
┌─────────────────────────────────────────────────────────────────────┐
│ ExecutionDetailView                                                  │
│                                                                      │
│  let execution: ToolExecution                                       │
│                                                                      │
│  Shows:                                                              │
│    - Tool name + prefixedName                                       │
│    - Request tab (JSON of parameters)                               │
│    - Response tab (JSON of response or error)                       │
│    - [Copy] [Retry] buttons                                         │
│                                                                      │
│  User clicks [Copy] → copies response.rawJSON to clipboard          │
│  User clicks [Retry] → queueManager.retryExecution(execution)       │
│  User clicks [Close] → selectedExecution = nil → back to tool list  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## ToolExecution State Machine (Detailed)

```
                     ┌──────────────────┐
                     │    CREATED       │
                     │  (in memory)     │
                     └────────┬─────────┘
                              │
                    User clicks Execute in sheet
                              │
                     ┌────────▼─────────┐
                     │ PENDING          │
                     │ (queued, waiting)│
                     │ status = .pending│
                     │ startedAt = nil  │
                     └────────┬─────────┘
                              │ (< 100ms)
                              │ Actually socket call starts
                              │
                     ┌────────▼──────────────┐
                     │ EXECUTING            │
                     │ (running)            │
                     │ status = .executing  │
                     │ startedAt = Date()   │
                     │ response = nil       │
                     └────────┬─────────────┘
                          ┌───┴───┐
                    _____|       |_____
                   /              \
                  /                \
             [TIMEOUT]          [RESPONSE OK]
              or [ERROR]              │
                  │                   │
            ┌─────▼──────┐      ┌─────▼──────────┐
            │ FAILURE    │      │ SUCCESS        │
            │ status =   │      │ status =       │
            │ .failure   │      │ .success       │
            │ error = "" │      │ response = {…} │
            │            │      │                │
            └─────┬──────┘      └─────┬──────────┘
                  │                   │
                  │    completedAt = Date()
                  │                   │
                  └────────┬──────────┘
                           │
                   (immediate or after 2s)
                           │
                  ┌────────▼──────────┐
                  │ MOVED TO HISTORY  │
                  │ (still inspectable)
                  │ removed from      │
                  │ activeExecutions[]│
                  │ added to          │
                  │ history[]         │
                  └───────────────────┘
                           │
                   User can:
                   - View response
                   - Retry (creates new ToolExecution)
                   - Clear history (removes all)
```

## SwiftUI Observable Pattern

```swift
// Primary observable (holds all state)
@Observable @MainActor
final class ExecutionQueueManager {
    @ObservationIgnored var socketServer: SocketServer?

    // These two properties trigger UI updates when changed
    private(set) var activeExecutions: [ToolExecution] = []
    private(set) var history: [ToolExecution] = []

    func executeToolAsync(tool: GatewayTool, request: ToolExecutionRequest) {
        let execution = ToolExecution(...)
        activeExecutions.append(execution)  // ← Triggers observation
        Task { await startExecution(execution) }  // ← Non-blocking
    }
}

// Secondary observable (contains mutating state)
@Observable @MainActor
final class ToolExecution {
    var status: ExecutionStatus = .pending  // ← Triggers observation
    var startedAt: Date?
    var completedAt: Date?
    var response: ToolExecutionResponse?
    var error: String?

    var elapsedSeconds: Double { /* computed */ }
    var displayStatus: String { /* computed */ }
}

// View observes and responds to changes
struct ExecutionQueuePanelView: View {
    @Environment(ExecutionQueueManager.self) var queueManager  // ← Access observable

    var body: some View {
        VStack {
            ForEach(queueManager.activeExecutions) { execution in  // ← Re-renders when array changes
                ExecutionQueueRowView(execution: execution)
                    // When execution.status changes, this row re-renders
            }
            ForEach(queueManager.history) { execution in
                ExecutionQueueRowView(execution: execution)
            }
        }
    }
}
```

## Key Patterns from Existing Shipyard Code

| Pattern | Used In | Applied To Queue |
|---------|---------|------------------|
| `@Observable @MainActor` | `MCPRegistry`, `GatewayRegistry`, `MCPServer` | `ExecutionQueueManager`, `ToolExecution` |
| Sidebar list + detail pane | `GatewayView` with servers | Queue entries as "selectable items" |
| `.onChange(of: registry.registeredServers)` | Tool auto-discovery | Watch `activeExecutions` for UI updates |
| `.sheet(isPresented:)` | Tool execution (new feature) | Follows existing modal pattern |
| Environment injection | `@Environment(GatewayRegistry)` | `@Environment(ExecutionQueueManager)` |
| Task { await ... } | `discoverTools()`, `toggleServer()` | `startExecution()` for non-blocking |
| Persistence with UserDefaults | Tool enable/disable state | Optional: persist panel height, history limit |

---

## Integration Points with Existing Code

### 1. **GatewayView Modifications**

**Current:**
```swift
struct GatewayView: View {
    @Environment(GatewayRegistry.self) private var gatewayRegistry
    @Environment(ProcessManager.self) private var processManager
    @Environment(MCPRegistry.self) private var registry

    var body: some View {
        NavigationSplitView {
            serverListView
        } detail: {
            detailView
        }
    }
}
```

**Modified:**
```swift
struct GatewayView: View {
    @Environment(GatewayRegistry.self) private var gatewayRegistry
    @Environment(ExecutionQueueManager.self) private var queueManager  // NEW
    @Environment(ProcessManager.self) private var processManager
    @Environment(MCPRegistry.self) private var registry

    @State private var selectedExecution: ToolExecution? = nil  // NEW
    @State private var showExecutionSheet = false              // NEW
    @State private var sheetTool: GatewayTool? = nil           // NEW

    var body: some View {
        VStack(spacing: 0) {
            NavigationSplitView {
                serverListView
            } detail: {
                detailView
            }

            Divider()

            ExecutionQueuePanelView(selectedExecution: $selectedExecution)  // NEW
        }
        .sheet(isPresented: $showExecutionSheet) {                          // NEW
            if let tool = sheetTool {
                ToolExecutionSheet(tool: tool, isPresented: $showExecutionSheet)
            }
        }
    }

    // Modify detailView to check for selectedExecution first
    @ViewBuilder
    private var detailView: some View {
        if let execution = selectedExecution {
            ExecutionDetailView(execution: execution, onClose: { selectedExecution = nil })
        } else if isShipyardSelected {
            shipyardCardView
        } else if let selectedServer = selectedServer {
            toolCatalogView(for: selectedServer)
        } else {
            shipyardCardView
        }
    }

    // Modify toolRow to add play button
    @ViewBuilder
    private func toolRow(tool: GatewayTool, isServerRunning: Bool) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(tool.originalName).font(.callout).fontWeight(.medium)
                if !tool.description.isEmpty {
                    Text(tool.description).font(.caption).foregroundStyle(.secondary)
                }
            }

            Spacer()

            Button(action: {
                sheetTool = tool
                showExecutionSheet = true
            }) {
                Image(systemName: "play.fill").font(.caption)
            }
            .buttonStyle(.plain)
            .help("Execute \(tool.originalName)")
            .disabled(!isServerRunning || !gatewayRegistry.isToolEnabled(tool.prefixedName))

            Toggle("", isOn: .init(
                get: { gatewayRegistry.isToolEnabled(tool.prefixedName) },
                set: { gatewayRegistry.setToolEnabled(tool.prefixedName, enabled: $0) }
            ))
            .toggleStyle(.switch)
            .disabled(!isServerRunning)
            .opacity(isServerRunning ? 1.0 : 0.5)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }
}
```

### 2. **ShipyardApp Modifications**

Where `GatewayRegistry` is injected, also inject `ExecutionQueueManager`:

```swift
@main
struct ShipyardApp: App {
    @State private var gatewayRegistry = GatewayRegistry()
    @State private var queueManager = ExecutionQueueManager()  // NEW
    @State private var registry = MCPRegistry()
    @State private var processManager = ProcessManager()

    var body: some Scene {
        WindowGroup {
            MainTabView()
                .environment(gatewayRegistry)
                .environment(queueManager)                      // NEW
                .environment(registry)
                .environment(processManager)
        }
    }
}
```

### 3. **SocketServer Modifications**

Add a `callTool()` method that bridges to existing gateway infrastructure:

```swift
// In SocketServer
@MainActor
func callTool(
    name: String,
    arguments: [String: AnyCodable]
) async throws -> ToolExecutionResponse {
    // 1. Find the tool in gatewayRegistry
    guard let tool = gatewayRegistry.tools.first(where: { $0.prefixedName == name }) else {
        throw ExecutionError.toolNotFound(name)
    }

    // 2. Route to correct child MCP or handle Shipyard tools
    if tool.mcpName == "shipyard" {
        // Handle Shipyard tools directly
        return try await handleShipyardTool(name: tool.originalName, arguments: arguments)
    } else {
        // Delegate to child MCP via existing Bridge infrastructure
        let bridge = processManager.bridge(for: server) ?? ...
        let response = try await bridge.callTool(name: name, arguments: arguments)
        return response
    }
}

enum ExecutionError: Error {
    case toolNotFound(String)
    case bridgeUnavailable
    case socketCallFailed(String)
}
```

---

## Threading & Concurrency Notes

### MainActor Usage

Both `ExecutionQueueManager` and `ToolExecution` are `@MainActor` to ensure:
1. **State mutations are synchronized** — All property updates happen on the main thread
2. **SwiftUI observation works** — ObservationTracking requires main thread
3. **UI updates are immediate** — No dispatch delays

### Non-Blocking Pattern

```swift
// In ToolExecutionSheet.execute():
func execute() {
    let request = ToolExecutionRequest(...)
    queueManager.executeToolAsync(tool, request: request)  // Returns immediately
    isPresented = false  // Sheet closes right away (~100ms)
}

// In ExecutionQueueManager.executeToolAsync():
func executeToolAsync(...) -> ToolExecution {
    let execution = ToolExecution(...)
    activeExecutions.append(execution)  // Observable triggers UI update

    Task {  // <-- Non-blocking: fire and forget
        await startExecution(execution)
    }

    return execution  // Return immediately, not waiting for Task
}

// async startExecution runs on main thread (MainActor),
// but doesn't block the UI because Task.sleep and network calls
// use Swift's cooperative threading model
```

### Why This Works

- `Task { await ... }` is non-blocking; control returns immediately
- Even though `startExecution()` is `async`, it uses `await` for socket calls
- Socket calls (`callTool`) don't block main thread; they're async/await based
- SwiftUI observation works because mutations happen on main thread (MainActor)

---

## Testing Strategy

### Unit Tests for ExecutionQueueManager

```swift
@Test func testExecuteToolReturnsImmediately() async {
    let manager = ExecutionQueueManager()
    let tool = makeTestTool()
    let request = ToolExecutionRequest(toolName: "test", arguments: [:])

    let startTime = Date()
    let execution = manager.executeToolAsync(tool, request: request)
    let elapsed = Date().timeIntervalSince(startTime)

    #expect(elapsed < 0.1)  // Should return in < 100ms
    #expect(execution.status == .pending)
    #expect(manager.activeExecutions.contains { $0.id == execution.id })
}

@Test func testExecutionMovesToHistoryAfterCompletion() async {
    let manager = ExecutionQueueManager()
    let mockServer = MockSocketServer()
    manager.socketServer = mockServer

    let execution = manager.executeToolAsync(makeTestTool(), request: ...)

    // Simulate completion
    try? await Task.sleep(for: .milliseconds(100))

    #expect(manager.activeExecutions.isEmpty)
    #expect(manager.history.first?.id == execution.id)
}
```

### Integration Tests

- Test sheet opens/closes correctly
- Test detail pane switches to ExecutionDetailView on row click
- Test undo/redo of retry operations (if added)

---

## Performance Considerations

1. **History limit:** Keep last 20 executions only (queue can get long)
2. **Lazy rendering:** Use LazyVStack if history grows beyond 50
3. **Memory:** Each ToolExecution holds response data in memory; clear old history
4. **Socket load:** Multiple concurrent executions should work; throttle if needed (future feature)

---

## Summary

The **Execution Queue** integrates into Shipyard using:

- **Architecture:** ExecutionQueueManager (Observable, MainActor) + ToolExecution model
- **UI:** Bottom panel with queue rows, detail pane shows full request/response
- **Integration:** Minimal changes to GatewayView, follows existing sidebar + detail pattern
- **Threading:** MainActor for safe state, Task { } for non-blocking execution
- **Patterns:** Reuses MCPRegistry, GatewayRegistry, SocketServer patterns from existing code

This design is **scalable** (handles many concurrent executions), **responsive** (non-blocking), and **consistent** with Shipyard's architecture.
