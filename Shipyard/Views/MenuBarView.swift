import SwiftUI
import AppKit
import ServiceManagement

struct MenuBarView: View {
    @Environment(MCPRegistry.self) private var registry
    @Environment(ProcessManager.self) private var processManager
    @State private var hoveredServerID: UUID?
    @State private var expandedSections: Set<String> = ["healthy", "config", "issues"]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Server list
            if registry.registeredServers.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "server.rack")
                        .font(.system(size: 24))
                        .foregroundStyle(.secondary)
                    Text("No servers found")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
            } else {
                // Partition servers by category
                let healthy = registry.registeredServers.filter { !$0.disabled && !$0.state.isError }
                let config = healthy.filter { $0.source == .config }
                let manifest = healthy.filter { $0.source != .config }
                let issues = registry.registeredServers.filter { !$0.disabled && $0.state.isError }
                let disabled = registry.registeredServers.filter { $0.disabled }

                VStack(alignment: .leading, spacing: 4) {
                    // Manifest-sourced healthy servers (no section header)
                    if !manifest.isEmpty {
                        ForEach(manifest) { server in
                            serverRow(for: server)
                        }
                    }

                    // Config-sourced section
                    if !config.isEmpty {
                        Divider()
                            .padding(.vertical, 2)
                        sectionHeader("Config", count: config.count, icon: "doc.json")
                        ForEach(config) { server in
                            serverRow(for: server)
                        }
                    }

                    // Issues section
                    if !issues.isEmpty {
                        Divider()
                            .padding(.vertical, 2)
                        sectionHeader("Issues", count: issues.count, icon: "exclamationmark.triangle.fill")
                        ForEach(issues) { server in
                            serverRow(for: server)
                        }
                    }

                    // Disabled section (collapsed by default)
                    if !disabled.isEmpty {
                        Divider()
                            .padding(.vertical, 2)
                        sectionHeader("Disabled", count: disabled.count, icon: "xmark.circle.fill", collapsible: true, isExpanded: expandedSections.contains("disabled"))

                        if expandedSections.contains("disabled") {
                            ForEach(disabled) { server in
                                serverRow(for: server)
                            }
                        }
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 8)
            }

            Divider()

            // Control buttons
            VStack(spacing: 6) {
                HStack(spacing: 8) {
                    Button(action: startAll) {
                        Image(systemName: "play.fill")
                    }
                    .help("Start All")

                    Button(action: stopAll) {
                        Image(systemName: "stop.fill")
                    }
                    .help("Stop All")

                    Spacer()

                    Button(action: openMainWindow) {
                        Label("Open Shipyard", systemImage: "arrow.up.right")
                            .font(.caption)
                    }
                    .help("Open main window")

                    Button(action: openSettings) {
                        Image(systemName: "gearshape")
                    }
                    .help("Open Settings")
                }

                // Launch-at-login indicator
                if SMAppService.mainApp.status == .enabled {
                    Text("Launches at login")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 8)

            Divider()

            // Quit button
            Button(action: { NSApplication.shared.terminate(nil) }) {
                Label("Quit Shipyard", systemImage: "power")
                    .font(.caption)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.red)
            .padding(.horizontal, 8)
            .padding(.vertical, 8)
        }
        .frame(width: 380)
        .padding(.vertical, 4)
    }
    
    // MARK: - Subviews

    @ViewBuilder
    private func sectionHeader(_ title: String, count: Int, icon: String, collapsible: Bool = false, isExpanded: Bool = true) -> some View {
        Button(action: { toggleSection(title) }) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                Text("\(title) (\(count))")
                if collapsible {
                    Spacer()
                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                }
            }
            .font(.caption.weight(.semibold))
            .textCase(.uppercase)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func serverRow(for server: MCPServer) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                // Status indicator
                if server.state == .starting || server.state == .stopping {
                    ProgressView()
                        .controlSize(.mini)
                        .frame(width: 10, height: 10)
                } else if server.disabled {
                    Circle()
                        .fill(Color.gray.opacity(0.4))
                        .frame(width: 10, height: 10)
                } else if case .error = server.state {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(ShipyardColors.error)
                } else {
                    Circle()
                        .fill(statusColor(for: server))
                        .frame(width: 10, height: 10)
                }

                // Server name and metadata
                HStack(spacing: 6) {
                    Text(server.manifest.name)
                        .font(.callout)
                        .fontWeight(.medium)
                        .lineLimit(1)

                    // Source badge for config-sourced
                    if server.source == .config {
                        Image(systemName: "doc.text")
                            .font(.system(size: 8))
                            .foregroundStyle(ShipyardColors.info)
                            .help("Configured via mcps.json")
                    }

                    Spacer()

                    // Status label
                    Text(statusLabel(for: server))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)

                    // Quick toggle or disabled badge
                    if server.disabled {
                        Text("Disabled")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    } else {
                        Button(action: { toggleServer(server) }) {
                            let iconName = server.state == .running ? "pause.fill" : "play.fill"
                            Image(systemName: iconName)
                                .font(.caption)
                                .foregroundStyle(Color.accentColor)
                        }
                        .buttonStyle(.plain)
                        .disabled(server.state == .starting || server.state == .stopping)
                        .help(server.state == .running ? "Pause" : "Start")
                    }
                }

                Spacer()
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)

            // Error message (if in error state)
            if case .error(let message) = server.state {
                Text(message)
                    .font(.caption)
                    .foregroundStyle(ShipyardColors.error)
                    .lineLimit(1)
                    .padding(.horizontal, 8)
                    .padding(.bottom, 4)
                    .help(message)
            }
        }
        .opacity(server.disabled ? 0.5 : 1.0)
        .onHover { isHovered in
            hoveredServerID = isHovered ? server.id : nil
        }
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(hoveredServerID == server.id ? Color.primary.opacity(0.06) : Color.clear)
        )
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
    
    // MARK: - Helpers

    private func statusColor(for server: MCPServer) -> Color {
        switch server.state {
        case .running:
            return ShipyardColors.running
        case .idle:
            return ShipyardColors.idle
        case .error:
            return ShipyardColors.error
        case .starting, .stopping:
            return ShipyardColors.transition
        }
    }

    private func statusLabel(for server: MCPServer) -> String {
        switch server.state {
        case .running:
            return "Running"
        case .idle:
            return "Idle"
        case .error:
            return "Error"
        case .starting:
            return "Starting..."
        case .stopping:
            return "Stopping..."
        }
    }

    private func toggleServer(_ server: MCPServer) {
        Task {
            switch server.state {
            case .running:
                await processManager.stop(server)
            default:
                do {
                    try await processManager.start(server)
                } catch {
                    server.state = .error("Failed to start")
                }
            }
        }
    }

    private func toggleSection(_ sectionName: String) {
        if expandedSections.contains(sectionName) {
            expandedSections.remove(sectionName)
        } else {
            expandedSections.insert(sectionName)
        }
    }

    private func startAll() {
        Task {
            for server in registry.registeredServers {
                if !server.disabled && server.state != .running {
                    do {
                        try await processManager.start(server)
                    } catch {
                        server.state = .error("Failed to start")
                    }
                }
            }
        }
    }

    private func stopAll() {
        Task {
            for server in registry.registeredServers {
                if !server.disabled && server.state == .running {
                    await processManager.stop(server)
                }
            }
        }
    }

    private func openMainWindow() {
        NSApp.activate(ignoringOtherApps: true)

        // Find and focus main window
        if let mainWindow = NSApp.windows.first(where: { !$0.title.contains("") }) {
            mainWindow.makeKeyAndOrderFront(nil)
        } else {
            // Try to open window by finding it in the app
            for window in NSApp.windows {
                if window.isVisible {
                    window.makeKeyAndOrderFront(nil)
                    return
                }
            }
        }
    }

    private func openSettings() {
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

// MARK: - ServerState Extensions

extension ServerState {
    var isError: Bool {
        if case .error = self {
            return true
        }
        return false
    }
}
