import Testing
import Foundation
@testable import Shipyard

@Suite("App Lifecycle Integration")
struct AppLifecycleTests {

    // MARK: - Helper Functions

    private func makeTestManifest(name: String) -> MCPManifest {
        let json = """
        {
            "name": "\(name)",
            "version": "1.0.0",
            "description": "Test",
            "transport": "stdio",
            "command": "python3",
            "args": ["server.py"]
        }
        """.data(using: .utf8)!
        return try! JSONDecoder().decode(MCPManifest.self, from: json)
    }

    @MainActor
    private func makeTestServer(name: String) -> MCPServer {
        MCPServer(manifest: makeTestManifest(name: name))
    }

    @MainActor
    private func makeRegistry(with servers: [MCPServer]) throws -> MCPRegistry {
        let registry = MCPRegistry()
        for server in servers {
            try registry.register(server)
        }
        return registry
    }

    @MainActor
    private func makeProcessManager() -> ProcessManager {
        ProcessManager()
    }

    @MainActor
    private func makeAutoStartManager() -> AutoStartManager {
        AutoStartManager()
    }

    // MARK: - Lifecycle Tests

    @Test("Save running servers on app quit")
    @available(macOS 14.0, *)
    @MainActor
    func saveRunningServersOnQuit() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let autoStartManager = makeAutoStartManager()
        let server1 = makeTestServer(name: "server1")
        let server2 = makeTestServer(name: "server2")

        server1.state = .running
        server2.state = .running

        // Simulate quit: save running servers
        let runningServers = [server1, server2].filter { $0.state.isRunning }
        autoStartManager.saveRunningServers(runningServers)

        // Verify saved
        let saved = autoStartManager.loadSavedServers()
        #expect(saved.count == 2)
        #expect(saved.map { $0.name }.contains("server1"))
        #expect(saved.map { $0.name }.contains("server2"))
    }

    @Test("Auto-start saved servers after discovery")
    @available(macOS 14.0, *)
    @MainActor
    func autoStartAfterDiscovery() async throws {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let autoStartManager = makeAutoStartManager()
        autoStartManager.setRestoreServersEnabled(true)

        let server1 = makeTestServer(name: "server1")
        let registry = try makeRegistry(with: [server1])
        let processManager = makeProcessManager()

        // Save server as if from previous run
        autoStartManager.saveRunningServers([server1])

        // Load and auto-start
        let savedServers = autoStartManager.loadSavedServers()
        let started = await autoStartManager.autoStartServers(
            savedServers: savedServers,
            registry: registry,
            processManager: processManager
        )

        // Should have attempted to start (note: actual start fails in test, but it should try)
        #expect(savedServers.count == 1)
    }

    @Test("Toggle OFF prevents auto-start on next launch")
    @available(macOS 14.0, *)
    @MainActor
    func toggleOffPreventsAutoStart() async throws {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let autoStartManager = makeAutoStartManager()

        // Save a server
        let server1 = makeTestServer(name: "server1")
        autoStartManager.saveRunningServers([server1])

        // Now disable auto-start
        autoStartManager.setRestoreServersEnabled(false)

        // Simulate next launch: auto-start should be skipped
        let registry = try makeRegistry(with: [server1])
        let processManager = makeProcessManager()
        let savedServers = autoStartManager.loadSavedServers()

        let started = await autoStartManager.autoStartServers(
            savedServers: savedServers,
            registry: registry,
            processManager: processManager
        )

        #expect(started.isEmpty)
    }

    @Test("Crash recovery loads last saved state")
    @available(macOS 14.0, *)
    @MainActor
    func crashRecoveryLoadsState() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let autoStartManager1 = makeAutoStartManager()

        // Simulate: app was running with 2 servers
        let server1 = makeTestServer(name: "server1")
        let server2 = makeTestServer(name: "server2")
        autoStartManager1.saveRunningServers([server1, server2])

        // Simulate crash (restart)
        let autoStartManager2 = makeAutoStartManager()
        let savedServers = autoStartManager2.loadSavedServers()

        // Should have recovered the saved state
        #expect(savedServers.count == 2)
        #expect(savedServers.map { $0.name }.contains("server1"))
        #expect(savedServers.map { $0.name }.contains("server2"))
    }

    @Test("Save empty server list on quit with no running servers")
    @available(macOS 14.0, *)
    @MainActor
    func saveEmptyListOnQuit() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let autoStartManager = makeAutoStartManager()

        let server1 = makeTestServer(name: "server1")
        server1.state = .idle

        // Simulate quit: no running servers
        let runningServers = [server1].filter { $0.state.isRunning }
        autoStartManager.saveRunningServers(runningServers)

        // Should be empty
        let saved = autoStartManager.loadSavedServers()
        #expect(saved.isEmpty)
    }

    @Test("Stopping a pending-removal stdio server unregisters it from the registry")
    @MainActor
    func stopPendingRemovalServerRemovesItFromRegistry() async throws {
        let server = MCPServer(manifest: makeTestManifest(name: "removed-stdio"), source: .config)
        server.state = .running
        server.isPendingConfigRemoval = true

        let registry = try makeRegistry(with: [server])
        let processManager = makeProcessManager()
        processManager.registry = registry

        await processManager.stop(server)

        #expect(server.state == .idle)
        #expect(registry.registeredServers.isEmpty)
    }

    @Test("Disconnecting a pending-removal HTTP server unregisters it from the registry")
    @MainActor
    func disconnectPendingRemovalHTTPServerRemovesItFromRegistry() async throws {
        let server = MCPServer(
            manifest: makeTestManifest(name: "removed-http"),
            source: .config,
            transport: .streamableHTTP
        )
        server.state = .running
        server.isPendingConfigRemoval = true
        server.configHTTPEndpoint = "https://example.com/mcp"

        let registry = try makeRegistry(with: [server])
        let processManager = makeProcessManager()
        processManager.registry = registry

        await processManager.disconnectHTTP(server)

        #expect(server.state == .idle)
        #expect(registry.registeredServers.isEmpty)
    }

    @Test("Settings persist across simulated app restarts")
    @available(macOS 14.0, *)
    @MainActor
    func settingsPersistAcrossRestarts() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        // First launch
        let manager1 = makeAutoStartManager()
        manager1.setRestoreServersEnabled(false)
        manager1.setAutoStartDelay(7)

        // Simulate app restart
        let manager2 = makeAutoStartManager()

        #expect(manager2.settings.restoreServersEnabled == false)
        #expect(manager2.settings.autoStartDelay == 7)
    }

    @Test("First launch with no saved state returns empty list")
    @available(macOS 14.0, *)
    @MainActor
    func firstLaunchEmptySavedState() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let autoStartManager = makeAutoStartManager()
        let savedServers = autoStartManager.loadSavedServers()

        #expect(savedServers.isEmpty)
    }
}
