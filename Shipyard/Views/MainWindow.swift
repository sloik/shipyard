import SwiftUI
import os
import ServiceManagement

private let log = Logger(subsystem: "com.shipyard.app", category: "MainWindow")

struct MainWindow: View {
    @Environment(MCPRegistry.self) private var registry
    @Environment(ProcessManager.self) private var processManager
    @Binding var selectedServer: MCPServer?
    let keychainManager: KeychainManager
    let socketServer: SocketServer

    @State private var selectedTab: NavigationTab = .servers
    @State private var launchAtLogin: Bool = false
    @State private var selectedGatewayServer: MCPServer?

    var body: some View {
        let _ = StartupProfiler.shared.recordFirstSceneRenderIfNeeded()

        TabView(selection: $selectedTab) {
            serversView
                .tabItem {
                    Label(NavigationTab.servers.rawValue, systemImage: NavigationTab.servers.icon)
                }
                .tag(NavigationTab.servers)

            GatewayView(socketServer: socketServer, selectedServer: $selectedGatewayServer)
                .tabItem {
                    Label(NavigationTab.gateway.rawValue, systemImage: NavigationTab.gateway.icon)
                }
                .tag(NavigationTab.gateway)

            SystemLogView()
                .tabItem {
                    Label(NavigationTab.logs.rawValue, systemImage: NavigationTab.logs.icon)
                }
                .tag(NavigationTab.logs)

            ConfigView(keychainManager: keychainManager)
                .tabItem {
                    Label(NavigationTab.config.rawValue, systemImage: NavigationTab.config.icon)
                }
                .tag(NavigationTab.config)

            SecretsView(keychainManager: keychainManager)
                .tabItem {
                    Label(NavigationTab.secrets.rawValue, systemImage: NavigationTab.secrets.icon)
                }
                .tag(NavigationTab.secrets)

            InstructionsView(keychainManager: keychainManager)
                .tabItem {
                    Label(NavigationTab.instructions.rawValue, systemImage: NavigationTab.instructions.icon)
                }
                .tag(NavigationTab.instructions)

            AboutView()
                .tabItem {
                    Label(NavigationTab.about.rawValue, systemImage: NavigationTab.about.icon)
                }
                .tag(NavigationTab.about)
        }
        .navigationTitle("Shipyard")
        .focusedValue(\.selectedTab, $selectedTab)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Toggle("Launch at Login", isOn: $launchAtLogin)
                    .controlSize(.small)
                    .help("Start Shipyard automatically when you log in")
                    .onChange(of: launchAtLogin) { _, newValue in
                        updateLaunchAtLogin(newValue)
                    }
            }
        }
        .onAppear {
            loadLaunchAtLoginStatus()
        }
        .onChange(of: registry.registeredServers) { _, servers in
            if let selectedServer, !servers.contains(where: { $0.id == selectedServer.id }) {
                self.selectedServer = nil
            }
        }
    }

    // MARK: - Servers View

    @ViewBuilder
    private var serversView: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                manifestImportBanner

                List(registry.sortedServers, selection: $selectedServer) { server in
                    MCPRowView(
                        server: server,
                        onStart: (server.source == .synthetic || server.isBuiltin) ? nil : { toggleServer(server) },
                        onStop: (server.source == .synthetic || server.isBuiltin) ? nil : { toggleServer(server) },
                        onRestart: server.isBuiltin ? { restartServer(server) } : (server.source == .synthetic ? nil : { restartServer(server) })
                    )
                        .tag(server)
                }
            }
            .overlay {
                if registry.registeredServers.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "server.rack")
                            .font(.system(size: 36))
                            .foregroundStyle(.secondary)
                        Text("No Servers Found")
                            .font(.headline)
                            .foregroundStyle(.secondary)
                        Text("Add servers to\n\(PathManager.shared.mcpsConfigFile.path)")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                            .multilineTextAlignment(.center)
                    }
                }
            }
            .navigationTitle("Servers")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    HStack(spacing: 4) {
                        Button(action: startAllServers) {
                            Label("Start All", systemImage: "play.fill")
                        }
                        .help("Start all servers")

                        Button(action: stopAllServers) {
                            Label("Stop All", systemImage: "stop.fill")
                        }
                        .help("Stop all servers")

                        Button(action: refreshServers) {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                        .help("Refresh server list (Cmd+R)")
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 260, max: 350)
        } detail: {
            if let selectedServer = selectedServer {
                VStack(spacing: 0) {
                    if selectedServer.isPendingConfigRemoval {
                        HStack(spacing: 12) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(ShipyardColors.warning)
                            Text("Removed from mcps.json. Stop this server to finish removal, or restore the config entry before restarting.")
                                .font(.callout)
                            Spacer()
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(.ultraThinMaterial)
                        .overlay(ShipyardColors.warning.opacity(0.08))
                        Divider()
                    }

                    // Error banner
                    if case .error(let message) = selectedServer.state {
                        HStack(spacing: 12) {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(ShipyardColors.error)
                            Text(message)
                                .font(.callout)
                            Spacer()
                            Button("Retry") {
                                toggleServer(selectedServer)
                            }
                            .buttonStyle(.bordered)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(.ultraThinMaterial)
                        .overlay(ShipyardColors.error.opacity(0.08))
                        Divider()
                    }

                    LogViewer(server: selectedServer, onNavigateToLogs: { selectedTab = .logs })
                }
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        HStack(spacing: 8) {
                            Toggle(
                                "Auto-Restart",
                                isOn: .init(
                                    get: { selectedServer.autoRestartEnabled },
                                    set: { selectedServer.autoRestartEnabled = $0 }
                                )
                            )
                            .help("Automatically restart if server crashes")
                            .disabled(selectedServer.source == .synthetic)

                            if selectedServer.isBuiltin {
                                Button(action: { restartServer(selectedServer) }) {
                                    Label("Restart", systemImage: "arrow.clockwise")
                                }
                                .help("Restart socket listener")
                                .disabled(selectedServer.state == .starting || selectedServer.state == .stopping)
                            } else if selectedServer.source != .synthetic {
                                Button(action: { toggleServer(selectedServer) }) {
                                    Label(
                                        selectedServer.state == .running ? "Stop" : "Start",
                                        systemImage: selectedServer.state == .running ? "stop.fill" : "play.fill"
                                    )
                                }
                                .help(selectedServer.state == .running ? "Stop server" : "Start server")
                                .disabled(selectedServer.state == .starting || selectedServer.state == .stopping)

                                Button(action: { restartServer(selectedServer) }) {
                                    Label("Restart", systemImage: "arrow.clockwise")
                                }
                                .help(selectedServer.isPendingConfigRemoval
                                    ? "Unavailable while this server is pending removal from mcps.json"
                                    : "Restart server")
                                .disabled(
                                    selectedServer.isPendingConfigRemoval ||
                                    selectedServer.state == .idle ||
                                    selectedServer.state == .starting ||
                                    selectedServer.state == .stopping
                                )
                            } else {
                                Label("Running", systemImage: "checkmark.circle.fill")
                                    .foregroundStyle(ShipyardColors.running)
                            }
                        }
                    }
                }
            } else {
                VStack(spacing: 16) {
                    Image(systemName: "square.and.arrow.up")
                        .font(.system(size: 48))
                        .foregroundStyle(.secondary)
                    Text("Select a Server")
                        .font(.title2)
                        .foregroundStyle(.secondary)
                    Text("Choose an MCP server from the list to view its logs and control it.")
                        .font(.body)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    // MARK: - Actions

    @ViewBuilder
    private var manifestImportBanner: some View {
        switch registry.manifestImportStatus {
        case .pending(let legacyCount):
            banner(
                systemImage: "clock.arrow.circlepath",
                text: legacyCount == 0
                    ? "Legacy manifest import pending"
                    : "Legacy manifest import pending (\(legacyCount) MCP\(legacyCount == 1 ? "" : "s"))",
                color: ShipyardColors.warning
            )
        case .imported(let imported, let skipped, let legacyCount):
            banner(
                systemImage: "checkmark.seal.fill",
                text: "Legacy import complete: \(imported) imported, \(skipped) skipped, \(legacyCount) total",
                color: ShipyardColors.info
            )
        case .noLegacyFound:
            banner(
                systemImage: "checkmark.circle",
                text: "No legacy manifest MCPs found",
                color: ShipyardColors.info
            )
        case .failed(let legacyCount, let message):
            banner(
                systemImage: "exclamationmark.triangle.fill",
                text: legacyCount == 0
                    ? "Legacy import failed: \(message)"
                    : "Legacy import failed for \(legacyCount) MCP\(legacyCount == 1 ? "" : "s"): \(message)",
                color: ShipyardColors.warning
            )
        }
    }

    private func banner(systemImage: String, text: String, color: Color) -> some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .foregroundStyle(color)
            Text(text)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(color.opacity(0.08))
    }

    private func refreshServers() {
        Task {
            do {
                try await registry.discover()
                await processManager.syncServers(from: registry)
            } catch {
                log.error("Discovery failed: \(error.localizedDescription)")
            }
        }
    }

    private func toggleServer(_ server: MCPServer) {
        guard !server.isBuiltin, server.source != .synthetic else { return }
        Task {
            switch server.state {
            case .running:
                await processManager.stop(server)
            default:
                do {
                    try await processManager.start(server)
                } catch {
                    server.state = .error(error.localizedDescription)
                    log.error("Failed to start '\(server.manifest.name)': \(error.localizedDescription)")
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
                    server.state = .error(error.localizedDescription)
                    log.error("Failed to restart socket listener: \(error.localizedDescription)")
                }
            } else {
                guard server.source != .synthetic else { return }
                do {
                    try await processManager.restart(server)
                } catch {
                    server.state = .error(error.localizedDescription)
                    log.error("Failed to restart '\(server.manifest.name)': \(error.localizedDescription)")
                }
            }
        }
    }

    private func startAllServers() {
        Task {
            for server in registry.registeredServers where
                server.source != .synthetic &&
                server.state != .running &&
                server.state != .starting
            {
                do {
                    try await processManager.start(server)
                } catch {
                    server.state = .error(error.localizedDescription)
                    log.error("Failed to start '\(server.manifest.name)': \(error.localizedDescription)")
                }
            }
        }
    }

    private func stopAllServers() {
        Task {
            for server in registry.registeredServers where
                server.source != .synthetic &&
                server.state == .running
            {
                await processManager.stop(server)
            }
        }
    }

    // MARK: - Launch at Login
    
    private func loadLaunchAtLoginStatus() {
        launchAtLogin = SMAppService.mainApp.status == .enabled
    }
    
    private func updateLaunchAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
                log.info("Launch at login enabled")
            } else {
                try SMAppService.mainApp.unregister()
                log.info("Launch at login disabled")
            }
        } catch {
            log.error("Failed to update launch at login: \(error.localizedDescription)")
            launchAtLogin = !enabled
        }
    }
}
