import AppKit
import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "GatewayView")

/// Gateway tab — aggregated tool catalog from all child MCPs, with NavigationSplitView
struct GatewayView: View {
    @Environment(GatewayRegistry.self) private var gatewayRegistry
    @Environment(ProcessManager.self) private var processManager
    @Environment(MCPRegistry.self) private var registry
    @Environment(ExecutionQueueManager.self) private var queueManager

    let socketServer: SocketServer
    @Binding var selectedServer: MCPServer?

    @State private var isDiscovering = false
    @State private var lastError: String?
    @State private var selectedExecution: ToolExecution?
    @State private var selectedToolForExecution: GatewayTool?
    @State private var sheetInitialArguments: [String: Any]?

    var body: some View {
        VStack(spacing: 0) {
            NavigationSplitView {
                serverListView
            } detail: {
                detailContent
            }
            .sheet(item: $selectedToolForExecution) { tool in
                ToolExecutionSheet(
                    tool: tool,
                    initialArguments: sheetInitialArguments,
                    onExecutionStarted: { execution in
                        selectedExecution = execution
                        sheetInitialArguments = nil
                    }
                )
            }
            
            ExecutionQueuePanelView(
                onViewExecution: { execution in
                    selectedExecution = execution
                },
                onRetryExecution: { execution in
                    // R3: Retry button opens the sheet pre-filled with the execution's parameters
                    sheetInitialArguments = execution.request.arguments
                    // Find and select the tool for this execution
                    if let tool = gatewayRegistry.tools.first(where: { $0.prefixedName == execution.toolName }) {
                        selectedToolForExecution = tool
                    }
                }
            )
        }
        .onChange(of: selectedServer) { _, newServer in
            guard let server = newServer else { return }
            let hasTools = gatewayRegistry.tools.contains { $0.mcpName == server.manifest.name }
            if server.state == .running && !hasTools {
                discoverTools(for: server)
            }
        }
        // Auto-discover tools when any server starts
        // Watch the registeredServers collection itself instead of a derived array
        // to avoid creating a new array identity on every evaluation
        .onChange(of: registry.registeredServers) { oldServers, newServers in
            // Only react to servers that transitioned to running state
            for newServer in newServers where newServer.state == .running {
                let wasRunning = oldServers.first { $0.id == newServer.id }?.state == .running
                guard !wasRunning else { continue }
                
                let hasTools = gatewayRegistry.tools.contains { $0.mcpName == newServer.manifest.name }
                if !hasTools {
                    discoverTools(for: newServer)
                }
            }
        }
        .task {
            _ = await gatewayRegistry.discoverShipyardTools()
            // Auto-discover tools for running servers on tab appear
            let needsDiscovery = registry.registeredServers.contains { server in
                server.state == .running && !gatewayRegistry.tools.contains { $0.mcpName == server.manifest.name }
            }
            if needsDiscovery {
                discover()
            }
        }
    }

    // MARK: - Sidebar: Server List

    @ViewBuilder
    private var serverListView: some View {
        List(registry.sortedServers, selection: $selectedServer) { server in
            GatewayServerRow(
                server: server,
                toolCount: gatewayRegistry.tools.filter { $0.mcpName == server.manifest.name }.count,
                isEnabled: gatewayRegistry.isMCPEnabled(server.manifest.name),
                onToggleEnabled: { gatewayRegistry.setMCPEnabled(server.manifest.name, enabled: $0) },
                onStart: { toggleServer(server) },
                onStop: { toggleServer(server) },
                onRestart: { restartServer(server) },
                isShipyard: server.source == .synthetic
            )
            .tag(server)
        }
        .navigationTitle("Servers")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                HStack(spacing: 8) {
                    Button(action: discover) {
                        Label(isDiscovering ? "Discovering..." : "Discover", systemImage: "arrow.clockwise")
                    }
                    .help("Discover tools from all running servers")
                    .disabled(isDiscovering)
                }
            }
        }
        .navigationSplitViewColumnWidth(min: 260, ideal: 300, max: 400)
    }

    // MARK: - Detail View

    @ViewBuilder
    private var detailContent: some View {
        if let execution = selectedExecution {
            // Show execution detail view
            ExecutionDetailView(
                execution: execution,
                onBack: { selectedExecution = nil },
                onRetry: { exec in
                    // R3: Retry button opens the sheet pre-filled with the execution's parameters
                    sheetInitialArguments = exec.request.arguments
                    // Find and select the tool for this execution
                    if let tool = gatewayRegistry.tools.first(where: { $0.prefixedName == exec.toolName }) {
                        selectedToolForExecution = tool
                    }
                },
                onFastRetry: { exec in
                    // Fast retry: immediately re-execute and auto-navigate
                    let newExecution = queueManager.retryExecution(exec)
                    selectedExecution = newExecution
                }
            )
        } else if let selectedServer = selectedServer {
            // Show tool catalog for selected server
            toolCatalogView(for: selectedServer)
        } else {
            emptyStateView
        }
    }

    // MARK: - Tool Catalog Detail

    @ViewBuilder
    private func toolCatalogView(for server: MCPServer) -> some View {
        let tools = gatewayRegistry.sortedTools(for: server.manifest.name)
        let totalTools = tools.count
        let enabledCount = tools.filter { $0.enabled }.count
        let isServerRunning = server.state == .running

        VStack(spacing: 0) {
            // Error banner
            if let lastError {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundStyle(.red)
                    Text(lastError)
                        .font(.callout)
                    Spacer()
                    Button(action: { self.lastError = nil }) {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(.ultraThinMaterial)
                .overlay(Color.red.opacity(0.08))
                Divider()
            }

            // Banner if server is stopped
            if !isServerRunning {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundStyle(.orange)
                    Text("Server is stopped. Start it to discover and toggle tools.")
                        .font(.callout)
                    Spacer()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(.ultraThinMaterial)
                .overlay(Color.orange.opacity(0.08))

                Divider()
            }

            if server.isPendingConfigRemoval {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    Text("This server was removed from mcps.json. Stop it to finish removal, or restore the config entry before restarting.")
                        .font(.callout)
                    Spacer()
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(.ultraThinMaterial)
                .overlay(Color.orange.opacity(0.08))

                Divider()
            }

            // Tools list or empty state
            if totalTools == 0 {
                noToolsStateView
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(tools, id: \.prefixedName) { tool in
                            toolRow(tool: tool, isServerRunning: isServerRunning)

                            if tool.prefixedName != tools.last?.prefixedName {
                                Divider()
                                    .padding(.vertical, 0)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }

                Divider()

                // Summary footer
                HStack(spacing: 12) {
                    Text("\(totalTools) tools")
                        .font(.callout)
                        .fontWeight(.semibold)

                    Spacer()

                    Text("(\(enabledCount) enabled)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
        }
    }

    // MARK: - No Tools State (within detail)

    @ViewBuilder
    private var noToolsStateView: some View {
        VStack(spacing: 16) {
            Image(systemName: "wrench.and.screwdriver")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("No Tools Discovered")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text("Start the server and tap Discover to see its tools.")
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Empty State (no server selected)

    @ViewBuilder
    private var emptyStateView: some View {
        VStack(spacing: 16) {
            Image(systemName: "network")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("Select a Server")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text("Choose an MCP server to manage its gateway tools.")
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Tool Row

    @ViewBuilder
    private func toolRow(tool: GatewayTool, isServerRunning: Bool) -> some View {
        let displayName = displayName(for: tool)
        HStack(spacing: 12) {
            // Clickable text area (wraps both title and description)
            VStack(alignment: .leading, spacing: 4) {
                Text(displayName)
                    .font(.callout)
                    .fontWeight(.medium)

                if !tool.description.isEmpty {
                    Text(tool.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .truncationMode(.tail)
                }
            }
            .contentShape(Rectangle())  // Make entire VStack clickable
            .onTapGesture {
                if let execution = lastExecutionForTool(tool.prefixedName) {
                    selectedExecution = execution
                }
            }

            Spacer()
                .contentShape(Rectangle())  // Make spacer also clickable
                .onTapGesture {
                    if let execution = lastExecutionForTool(tool.prefixedName) {
                        selectedExecution = execution
                    }
                }

            // Play button to execute tool (NOT clickable via row tap)
            Button(action: { selectedToolForExecution = tool }) {
                Image(systemName: "play.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.blue)
            }
            .buttonStyle(.plain)
            .help("Execute \(displayName)")
            .disabled(!isServerRunning)
            .opacity(isServerRunning ? 1.0 : 0.5)
            .contentShape(Rectangle())
            .padding(4)

            // Toggle to enable/disable tool (NOT clickable via row tap)
            Toggle("", isOn: .init(
                get: { gatewayRegistry.isToolEnabled(tool.prefixedName) },
                set: { gatewayRegistry.setToolEnabled(tool.prefixedName, enabled: $0) }
            ))
            .toggleStyle(.switch)
            .help(isServerRunning
                ? (gatewayRegistry.isToolEnabled(tool.prefixedName)
                    ? "Disable: hide \(displayName) from Gateway clients"
                    : "Enable: expose \(displayName) to Gateway clients")
                : "Start the server to toggle individual tools")
            .disabled(!isServerRunning)
            .opacity(isServerRunning ? 1.0 : 0.5)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .foregroundStyle(isServerRunning ? .primary : .tertiary)
    }

    // MARK: - Execution Lookup

    /// Find the most recent execution for a tool by prefixedName.
    /// Searches activeExecutions first (newest), then history (newest first).
    private func lastExecutionForTool(_ toolName: String) -> ToolExecution? {
        // Check active executions first (in reverse order to get the most recent)
        if let active = queueManager.activeExecutions.last(where: { $0.toolName == toolName }) {
            return active
        }
        // Then check history (already ordered with newest first)
        return queueManager.history.first(where: { $0.toolName == toolName })
    }

    // MARK: - Actions

    private func toggleServer(_ server: MCPServer) {
        guard !server.isBuiltin else { return }
        Task {
            switch server.state {
            case .running:
                await processManager.stop(server)
            default:
                do {
                    try await processManager.start(server)
                } catch {
                    let msg = error.localizedDescription
                    server.state = .error(msg)
                    log.error("Failed to start '\(server.manifest.name)': \(msg)")
                }
            }
        }
    }

    private func restartServer(_ server: MCPServer) {
        Task {
            if server.isBuiltin {
                server.state = .stopping
                do {
                    try await socketServer.restartSocketListener()
                    server.state = .running
                } catch {
                    let msg = error.localizedDescription
                    server.state = .error(msg)
                    log.error("Failed to restart socket listener: \(msg)")
                }
            } else {
                do {
                    try await processManager.restart(server)
                } catch {
                    let msg = error.localizedDescription
                    server.state = .error(msg)
                    log.error("Failed to restart '\(server.manifest.name)': \(msg)")
                }
            }
        }
    }

    private func discoverTools(for server: MCPServer) {
        guard !isDiscovering else { return }
        isDiscovering = true
        Task {
            defer { isDiscovering = false }
            do {
                let toolCount = try await gatewayRegistry.discoverTools(for: server, processManager: processManager)
                log.info("Auto-discovered \(toolCount) tools from \(server.manifest.name)")
            } catch {
                let msg = error.localizedDescription
                lastError = "Discovery failed for \(server.manifest.name): \(msg)"
                log.error("Auto-discover failed for \(server.manifest.name): \(msg)")
            }
        }
    }

    private func discover() {
        isDiscovering = true
        Task {
            defer { isDiscovering = false }
            _ = await gatewayRegistry.discoverShipyardTools()
            for server in registry.registeredServers where server.state == .running {
                do {
                    let toolCount = try await gatewayRegistry.discoverTools(for: server, processManager: processManager)
                    log.info("Discovered \(toolCount) tools from \(server.manifest.name)")
                } catch {
                    let msg = error.localizedDescription
                    lastError = "Discovery failed for \(server.manifest.name): \(msg)"
                    log.error("Failed to discover tools for \(server.manifest.name): \(msg)")
                }
            }
        }
    }

    private func displayName(for tool: GatewayTool) -> String {
        guard tool.mcpName == GatewayRegistry.shipyardMCPName,
              tool.originalName.hasPrefix("shipyard_") else {
            return tool.originalName
        }
        return String(tool.originalName.dropFirst("shipyard_".count))
    }
}

// MARK: - Gateway Server Row (Sidebar Item)

struct GatewayServerRow: View {
    let server: MCPServer
    let toolCount: Int
    let isEnabled: Bool
    let onToggleEnabled: (Bool) -> Void
    let onStart: () -> Void
    let onStop: () -> Void
    let onRestart: () -> Void
    let isShipyard: Bool

    var statusColor: Color {
        switch server.state {
        case .running:
            return .green
        case .idle:
            return .gray
        case .error:
            return .red
        case .starting, .stopping:
            return .yellow
        }
    }

    var body: some View {
        HStack(spacing: 8) {
            // Status indicator
            if server.state == .starting || server.state == .stopping {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 8, height: 8)
            } else {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)
            }

            // Server name and tool count
            VStack(alignment: .leading, spacing: 2) {
                Text(server.manifest.name)
                    .font(.callout)
                    .fontWeight(.medium)

                Text("\(toolCount) tools")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            // Enable/disable toggle
            if isShipyard {
                Text("Built-in")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            } else {
                HStack(spacing: 4) {
                    Text("Gateway")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Toggle("", isOn: .init(
                        get: { isEnabled },
                        set: { onToggleEnabled($0) }
                    ))
                    .toggleStyle(.switch)
                    .help(isEnabled
                        ? "Disable: hide all \(server.manifest.name) tools from Gateway clients"
                        : "Enable: expose \(server.manifest.name) tools to Gateway clients")
                }
            }
        }
        .contextMenu {
            if server.state == .running {
                if !isShipyard {
                    Button(action: onStop) {
                        Label("Stop", systemImage: "stop.fill")
                    }
                    .disabled(server.state == .starting || server.state == .stopping)
                }

                Button(action: onRestart) {
                    Label("Restart", systemImage: "arrow.clockwise")
                }
                .disabled(server.isPendingConfigRemoval || server.state == .starting || server.state == .stopping)
            } else if !isShipyard {
                    Button(action: onStart) {
                        Label("Start", systemImage: "play.fill")
                    }
                    .disabled(server.state == .starting || server.state == .stopping)
            }
            if server.state == .running || !isShipyard {
                Divider()
            }

            Button(action: { revealLogInFinder() }) {
                Label("Reveal Log in Finder", systemImage: "doc.text.magnifyingglass")
            }
            Button(action: { openLogsFolder() }) {
                Label("Open Logs Folder", systemImage: "folder")
            }
        }
    }

    // MARK: - Log File Access

    private func revealLogInFinder() {
        let logDir = PathManager.shared.mcpLogDirectory(for: server.manifest.name)
        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy-MM-dd"
        let todayFile = logDir.appendingPathComponent("\(dateFormatter.string(from: Date())).log")
        if FileManager.default.fileExists(atPath: todayFile.path) {
            NSWorkspace.shared.activateFileViewerSelecting([todayFile])
        } else {
            NSWorkspace.shared.open(logDir)
        }
    }

    private func openLogsFolder() {
        NSWorkspace.shared.open(PathManager.shared.logsDirectory)
    }
}

#Preview {
    @Previewable @State var gateway = GatewayRegistry()
    @Previewable @State var registry = MCPRegistry()
    @Previewable @State var processManager = ProcessManager()
    @Previewable @State var socketServer = SocketServer()
    @Previewable @State var queueManager = ExecutionQueueManager()
    @Previewable @State var selectedServer: MCPServer? = nil

    GatewayView(socketServer: socketServer, selectedServer: $selectedServer)
        .environment(gateway)
        .environment(registry)
        .environment(processManager)
        .environment(queueManager)
}
