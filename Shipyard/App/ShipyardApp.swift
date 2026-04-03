import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ShipyardApp")

@main
struct ShipyardApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate

    @State private var registry = MCPRegistry()
    @State private var processManager = ProcessManager()
    @State private var healthChecker = HealthChecker()
    @State private var socketServer = SocketServer()
    @State private var gatewayRegistry = GatewayRegistry()
    @State private var executionQueueManager = ExecutionQueueManager()
    @State private var logStore = LogStore()
    @State private var autoStartManager = AutoStartManager()
    @State private var selectedServer: MCPServer?
    @State private var configFileWatcher = ConfigFileWatcher()
    @State private var didRegisterConfigSaveObserver = false

    /// Keychain manager — shared across views for secret storage
    private let keychainManager = KeychainManager()

    /// App logger — writes structured JSONL to the centralized runtime log path.
    private let appLogger = AppLogger()

    init() {
        StartupProfiler.shared.reset()
        StartupProfiler.shared.begin("ShipyardApp.init")
        StartupProfiler.shared.end("ShipyardApp.init")
    }

    var body: some Scene {
        WindowGroup {
            MainWindow(
                selectedServer: $selectedServer,
                keychainManager: keychainManager,
                socketServer: socketServer
            )
            .environment(registry)
            .environment(processManager)
            .environment(gatewayRegistry)
            .environment(executionQueueManager)
            .environment(logStore)
            .environment(autoStartManager)
            .task {
                let profiler = StartupProfiler.shared
                profiler.begin("startup.task")

                @MainActor
                func finishStartupProfiling(success: Bool) {
                    let report = profiler.completeStartup()
                    let reportLine = profiler.reportJSONString(prettyPrinted: false)

                    appLogger.log(
                        .info,
                        cat: "startup-profile",
                        msg: reportLine,
                        meta: [
                            "success": .bool(success),
                            "total_ms": .double(report.totalMs),
                            "phase_count": .int(report.phases.count),
                            "server_count": .int(report.servers.count)
                        ]
                    )

                    if report.totalMs > 4_000 {
                        let top = profiler.topSlowPhases(limit: 3)
                        let bottlenecks = top
                            .map { "\($0.label) (\(String(format: "%.0f", $0.durationMs))ms)" }
                            .joined(separator: ", ")
                        appLogger.log(
                            .warn,
                            cat: "startup-profile",
                            msg: "Startup exceeded 4s",
                            meta: [
                                "total_ms": .double(report.totalMs),
                                "top_3": .string(bottlenecks)
                            ]
                        )
                    }
                }

                log.info("ShipyardApp .task — starting discovery")

                // Wire Keychain manager into ProcessManager
                processManager.keychainManager = keychainManager
                processManager.registry = registry
                processManager.autoStartManager = autoStartManager

                // Wire AppLogger into LogStore
                appLogger.logStore = logStore

                do {
                    let setup = try PathManager.shared.prepareRuntimeLayout()
                    appLogger.log(
                        .info,
                        cat: "paths",
                        msg: "Runtime layout ready",
                        meta: [
                            "profile": .string(PathManager.shared.profile.rawValue),
                            "created_dirs": .int(setup.createdDirectories.count),
                            "bridge_copied": .bool(setup.copiedBridgeBinary)
                        ]
                    )
                } catch {
                    appLogger.log(.warn, cat: "paths", msg: "Runtime setup incomplete", meta: ["error": .string(error.localizedDescription)])
                }

                // Load logs from both bridge and app
                logStore.loadFromDisk()

                // Wire AppLogger into services
                registry.appLogger = appLogger
                processManager.appLogger = appLogger
                gatewayRegistry.appLogger = appLogger
                autoStartManager.appLogger = appLogger

                appLogger.log(.info, cat: "lifecycle", msg: "Shipyard launched")

                if !didRegisterConfigSaveObserver {
                    didRegisterConfigSaveObserver = true
                    NotificationCenter.default.addObserver(
                        forName: .shipyardConfigDidSave,
                        object: nil,
                        queue: .main
                    ) { [registry, processManager] _ in
                        Task { @MainActor in
                            await registry.reloadConfig()
                            await processManager.syncServers(from: registry)
                        }
                    }
                }

                do {
                    let manifestImportRun = await ManifestImporter().runIfNeeded()
                    registry.setManifestImportStatus(manifestImportRun.status)
                    registry.setManifestDiscoveryReadOnly(manifestImportRun.manifestDiscoveryIsReadOnly)

                    switch manifestImportRun.status {
                    case .pending(let legacyCount):
                        appLogger.log(.info, cat: "import", msg: "Manifest import pending", meta: ["legacy_count": .int(legacyCount)])
                    case .imported(let imported, let skipped, let legacyCount):
                        appLogger.log(
                            .info,
                            cat: "import",
                            msg: "Manifest import complete",
                            meta: [
                                "imported": .int(imported),
                                "skipped": .int(skipped),
                                "legacy_count": .int(legacyCount)
                            ]
                        )
                    case .noLegacyFound:
                        appLogger.log(.info, cat: "import", msg: "No legacy manifests found")
                    case .failed(let legacyCount, let message):
                        appLogger.log(
                            .warn,
                            cat: "import",
                            msg: "Manifest import failed; legacy discovery remains writable",
                            meta: [
                                "legacy_count": .int(legacyCount),
                                "error": .string(message)
                            ]
                        )
                    }

                    // Load manifest-sourced MCPs
                    profiler.markInstant("discovery.begin")
                    profiler.begin("discovery")
                    try await registry.discover()
                    profiler.end("discovery")
                    profiler.markInstant("discovery.complete")
                    
                    // Load config-sourced MCPs
                    profiler.markInstant("loadConfig.begin")
                    profiler.begin("loadConfig")
                    await registry.loadConfig()
                    profiler.end("loadConfig")
                    profiler.markInstant("loadConfig.complete")
                    
                    await processManager.syncServers(from: registry)

                    let savedServers = autoStartManager.loadSavedServers()
                    profiler.markInstant("autoStart.begin")
                    profiler.begin("autoStart")
                    _ = await autoStartManager.autoStartServers(
                        savedServers: savedServers,
                        registry: registry,
                        processManager: processManager
                    )
                    profiler.end("autoStart")
                    profiler.markInstant("autoStart.complete")

                    profiler.begin("toolDiscovery")
                    for server in registry.registeredServers where server.state == .running {
                        _ = try? await gatewayRegistry.discoverTools(for: server, processManager: processManager)
                    }
                    profiler.end("toolDiscovery")

                    // Start health checks for all servers
                    for server in registry.registeredServers {
                        healthChecker.startHealthChecks(for: server, processManager: processManager)
                    }

                    // Start socket server
                    await socketServer.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry, appLogger: appLogger)
                    gatewayRegistry.setSocketServer(socketServer)
                    _ = await gatewayRegistry.discoverShipyardTools()

                    // Wire socket server into execution queue manager
                    executionQueueManager.setSocketServer(socketServer)

                    // Set up config file watcher for live updates
                    configFileWatcher.appLogger = appLogger
                    configFileWatcher.onConfigChanged = { [weak registry] in
                        guard let registry else { return }
                        await registry.reloadConfig()
                        await processManager.syncServers(from: registry)
                    }
                    configFileWatcher.start()

                    appLogger.log(.info, cat: "lifecycle", msg: "Discovery complete", meta: ["server_count": .int(registry.registeredServers.count)])
                    log.info("ShipyardApp .task — discovery complete, \(registry.registeredServers.count) servers")
                    profiler.end("startup.task")
                    finishStartupProfiling(success: true)
                } catch {
                    appLogger.log(.error, cat: "lifecycle", msg: "Discovery failed", meta: ["error": .string(error.localizedDescription)])
                    log.error("ShipyardApp discovery failed: \(error.localizedDescription)")
                    profiler.end("startup.task")
                    finishStartupProfiling(success: false)
                }
            }
            .frame(minWidth: 600, minHeight: 400)
        }
        .defaultSize(width: 1000, height: 600)
        .commands {
            ShipyardCommands(registry: registry, processManager: processManager, logStore: logStore)
        }

        // Settings window
        Settings {
            SettingsView()
                .environment(autoStartManager)
                .environment(registry)
        }
    }
}
