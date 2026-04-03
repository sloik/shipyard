import Testing
import Foundation
@testable import Shipyard

@Suite("AutoStartManager")
struct AutoStartManagerTests {

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

    // MARK: - Settings Tests

    @Test("Load default settings on init")
    @available(macOS 14.0, *)
    @MainActor
    func loadDefaultSettings() {
        // Clear any existing settings
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        let manager = AutoStartManager()
        #expect(manager.settings.restoreServersEnabled == true)
        #expect(manager.settings.autoStartDelay == 2)
    }

    @Test("Save and load settings")
    @available(macOS 14.0, *)
    @MainActor
    func saveAndLoadSettings() {
        // Clear
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        let manager = AutoStartManager()
        manager.setRestoreServersEnabled(false)
        manager.setAutoStartDelay(5)

        // Create new manager and verify settings loaded
        let manager2 = AutoStartManager()
        #expect(manager2.settings.restoreServersEnabled == false)
        #expect(manager2.settings.autoStartDelay == 5)
    }

    @Test("Clamp delay to 1-10 range")
    @available(macOS 14.0, *)
    @MainActor
    func clampDelayRange() {
        let manager = AutoStartManager()

        manager.setAutoStartDelay(0)
        #expect(manager.settings.autoStartDelay == 1)

        manager.setAutoStartDelay(15)
        #expect(manager.settings.autoStartDelay == 10)

        manager.setAutoStartDelay(5)
        #expect(manager.settings.autoStartDelay == 5)
    }

    @Test("setRestoreServersEnabled updates and persists")
    @available(macOS 14.0, *)
    @MainActor
    func setRestoreServersEnabled() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        let manager = AutoStartManager()
        manager.setRestoreServersEnabled(false)

        let manager2 = AutoStartManager()
        #expect(manager2.settings.restoreServersEnabled == false)
    }

    // MARK: - Save/Load Running Servers

    @Test("Save running servers")
    @available(macOS 14.0, *)
    @MainActor
    func saveRunningServers() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let manager = AutoStartManager()
        let server1 = makeTestServer(name: "server1")
        let server2 = makeTestServer(name: "server2")

        manager.saveRunningServers([server1, server2])

        let saved = manager.loadSavedServers()
        #expect(saved.count == 2)
        #expect(saved[0].name == "server1")
        #expect(saved[1].name == "server2")
    }

    @Test("Load saved servers")
    @available(macOS 14.0, *)
    @MainActor
    func loadSavedServers() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let manager = AutoStartManager()
        let servers = [makeTestServer(name: "test1"), makeTestServer(name: "test2")]
        manager.saveRunningServers(servers)

        let loaded = manager.loadSavedServers()
        #expect(loaded.count == 2)
        #expect(loaded.allSatisfy { $0.timestamp != nil })
    }

    @Test("Load saved servers when none exist")
    @available(macOS 14.0, *)
    @MainActor
    func loadSavedServersWhenNone() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let manager = AutoStartManager()
        let loaded = manager.loadSavedServers()
        #expect(loaded.isEmpty)
    }

    @Test("Clear saved servers")
    @available(macOS 14.0, *)
    @MainActor
    func clearSavedServers() {
        let manager = AutoStartManager()
        let servers = [makeTestServer(name: "test")]
        manager.saveRunningServers(servers)

        manager.clearSavedServers()

        let loaded = manager.loadSavedServers()
        #expect(loaded.isEmpty)
    }

    @Test("Handle corrupted UserDefaults entry")
    @available(macOS 14.0, *)
    @MainActor
    func handleCorruptedData() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        // Store invalid JSON
        UserDefaults.standard.set("invalid json".data(using: .utf8), forKey: AutoStartManager.autoStartLastRunningKey)

        let manager = AutoStartManager()
        let loaded = manager.loadSavedServers()

        // Should return empty and clean up
        #expect(loaded.isEmpty)
        // Verify it was removed
        let loaded2 = manager.loadSavedServers()
        #expect(loaded2.isEmpty)
    }

    // MARK: - Auto-Start Sequential Logic

    @Test("Auto-start respects disabled setting")
    @available(macOS 14.0, *)
    @MainActor
    func autoStartDisabled() async throws {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let manager = AutoStartManager()
        manager.setRestoreServersEnabled(false)

        let server1 = makeTestServer(name: "server1")
        let registry = try makeRegistry(with: [server1])
        let processManager = makeProcessManager()

        let saved = [SavedMCPServer(id: server1.id, name: "server1", timestamp: Date())]
        let started = await manager.autoStartServers(savedServers: saved, registry: registry, processManager: processManager)

        #expect(started.isEmpty)
    }

    @Test("Auto-start with empty saved servers")
    @available(macOS 14.0, *)
    @MainActor
    func autoStartEmpty() async throws {
        let manager = AutoStartManager()
        let registry = try makeRegistry(with: [])
        let processManager = makeProcessManager()

        let started = await manager.autoStartServers(savedServers: [], registry: registry, processManager: processManager)

        #expect(started.isEmpty)
    }

    @Test("Auto-start skips missing servers")
    @available(macOS 14.0, *)
    @MainActor
    func autoStartSkipsMissing() async throws {
        let manager = AutoStartManager()
        manager.setRestoreServersEnabled(true)

        // Registry is empty
        let registry = try makeRegistry(with: [])
        let processManager = makeProcessManager()

        let missingId = UUID()
        let saved = [SavedMCPServer(id: missingId, name: "missing", timestamp: Date())]

        let started = await manager.autoStartServers(savedServers: saved, registry: registry, processManager: processManager)

        #expect(started.isEmpty)
    }

    @Test("Auto-start delay setting is configurable")
    @available(macOS 14.0, *)
    @MainActor
    func autoStartDelayConfigurable() {
        let manager = AutoStartManager()

        manager.setAutoStartDelay(3)
        #expect(manager.settings.autoStartDelay == 3)

        manager.setAutoStartDelay(7)
        #expect(manager.settings.autoStartDelay == 7)
    }

    // MARK: - Edge Cases

    @Test("Save empty server list")
    @available(macOS 14.0, *)
    @MainActor
    func saveEmptyServerList() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartLastRunningKey)

        let manager = AutoStartManager()
        manager.saveRunningServers([])

        let loaded = manager.loadSavedServers()
        #expect(loaded.isEmpty)
    }

    @Test("Settings validation clamps values")
    @available(macOS 14.0, *)
    @MainActor
    func settingsValidationClamps() {
        var settings = AutoStartSettings()
        settings.autoStartDelay = -5
        settings.validateDelay()
        #expect(settings.autoStartDelay == 1)

        settings.autoStartDelay = 100
        settings.validateDelay()
        #expect(settings.autoStartDelay == 10)
    }

    @Test("Load settings with invalid data preserves defaults")
    @available(macOS 14.0, *)
    @MainActor
    func loadSettingsWithInvalidData() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)
        // Set invalid data
        UserDefaults.standard.set("bad data".data(using: .utf8), forKey: AutoStartManager.autoStartSettingsKey)

        let manager = AutoStartManager()
        // Should load defaults
        #expect(manager.settings.restoreServersEnabled == true)
        #expect(manager.settings.autoStartDelay == 2)
    }
}
