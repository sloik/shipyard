import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "AutoStartManager")

// MARK: - Models

/// Settings for auto-start behavior
struct AutoStartSettings: Codable {
    /// Whether auto-start is enabled on app launch
    var restoreServersEnabled: Bool = true
    /// Delay in seconds between sequential server starts (1-10s, default 2s)
    var autoStartDelay: Int = 2

    /// Validate and clamp delay to valid range
    mutating func validateDelay() {
        autoStartDelay = max(1, min(10, autoStartDelay))
    }
}

/// Represents a saved MCP server for auto-start (minimal data)
struct SavedMCPServer: Codable {
    let id: UUID
    let name: String
    let timestamp: Date
}

// MARK: - AutoStartManager

/// Manages persistence and sequential auto-start of MCP servers
@Observable @MainActor final class AutoStartManager {
    /// Key for storing the list of running servers
    static let autoStartLastRunningKey = "autoStartLastRunning"
    /// Key for storing auto-start settings
    static let autoStartSettingsKey = "autoStartSettings"

    /// App logger — injected
    var appLogger: AppLogger?

    /// Current auto-start settings
    private(set) var settings = AutoStartSettings()

    init() {
        log.info("AutoStartManager initialized")
        loadSettings()
    }

    // MARK: - Settings Management

    /// Load settings from UserDefaults
    func loadSettings() {
        let defaults = UserDefaults.standard

        if let data = defaults.data(forKey: Self.autoStartSettingsKey) {
            do {
                var loaded = try JSONDecoder().decode(AutoStartSettings.self, from: data)
                loaded.validateDelay()
                self.settings = loaded
                log.info("Loaded auto-start settings: restoreEnabled=\(loaded.restoreServersEnabled), delay=\(loaded.autoStartDelay)s")
            } catch {
                log.error("Failed to decode auto-start settings: \(error.localizedDescription)")
                appLogger?.log(.error, cat: "autostart", msg: "Failed to load settings", meta: ["error": .string(error.localizedDescription)])
                // Keep default settings
            }
        } else {
            log.info("No saved settings found, using defaults")
        }
    }

    /// Save settings to UserDefaults
    func saveSettings() {
        let defaults = UserDefaults.standard

        do {
            var toSave = settings
            toSave.validateDelay()
            let data = try JSONEncoder().encode(toSave)
            defaults.set(data, forKey: Self.autoStartSettingsKey)
            log.info("Saved auto-start settings: restoreEnabled=\(toSave.restoreServersEnabled), delay=\(toSave.autoStartDelay)s")
            appLogger?.log(.debug, cat: "autostart", msg: "Settings saved")
        } catch {
            log.error("Failed to encode auto-start settings: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "autostart", msg: "Failed to save settings", meta: ["error": .string(error.localizedDescription)])
        }
    }

    /// Update restore servers setting
    func setRestoreServersEnabled(_ enabled: Bool) {
        settings.restoreServersEnabled = enabled
        saveSettings()
    }

    /// Update auto-start delay (will be clamped to 1-10s)
    func setAutoStartDelay(_ seconds: Int) {
        settings.autoStartDelay = max(1, min(10, seconds))
        saveSettings()
    }

    // MARK: - Save/Load Running Servers

    /// Save currently running servers to UserDefaults
    /// - Parameter servers: Array of MCPServer instances that are running
    func saveRunningServers(_ servers: [MCPServer]) {
        let defaults = UserDefaults.standard

        let saved = servers.map { server in
            SavedMCPServer(
                id: server.id,
                name: server.manifest.name,
                timestamp: Date()
            )
        }

        do {
            let data = try JSONEncoder().encode(saved)
            defaults.set(data, forKey: Self.autoStartLastRunningKey)
            log.info("Saved \(saved.count) running servers to UserDefaults")
            appLogger?.log(.info, cat: "autostart", msg: "Saved running servers", meta: ["count": .int(saved.count)])
        } catch {
            log.error("Failed to encode running servers: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "autostart", msg: "Failed to save running servers", meta: ["error": .string(error.localizedDescription)])
        }
    }

    /// Load saved servers from UserDefaults
    /// - Returns: Array of SavedMCPServer
    func loadSavedServers() -> [SavedMCPServer] {
        let defaults = UserDefaults.standard

        guard let data = defaults.data(forKey: Self.autoStartLastRunningKey) else {
            log.info("No saved servers found")
            return []
        }

        do {
            let saved = try JSONDecoder().decode([SavedMCPServer].self, from: data)
            log.info("Loaded \(saved.count) saved servers from UserDefaults")
            return saved
        } catch {
            log.error("Failed to decode saved servers: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "autostart", msg: "Failed to load saved servers", meta: ["error": .string(error.localizedDescription)])
            // Clean up corrupted data
            defaults.removeObject(forKey: Self.autoStartLastRunningKey)
            return []
        }
    }

    /// Clear saved servers from UserDefaults
    func clearSavedServers() {
        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: Self.autoStartLastRunningKey)
        log.info("Cleared saved servers")
        appLogger?.log(.debug, cat: "autostart", msg: "Saved servers cleared")
    }

    // MARK: - Auto-Start Logic

    /// Sequentially auto-start saved MCPs that are still registered
    /// - Parameters:
    ///   - savedServers: List of SavedMCPServer from loadSavedServers()
    ///   - registry: MCPRegistry to check if servers still exist
    ///   - processManager: ProcessManager to start servers
    /// - Returns: List of servers that were successfully started
    func autoStartServers(
        savedServers: [SavedMCPServer],
        registry: MCPRegistry,
        processManager: ProcessManager
    ) async -> [MCPServer] {
        // If auto-start disabled, skip
        guard settings.restoreServersEnabled else {
            log.info("Auto-start disabled, skipping auto-start")
            appLogger?.log(.debug, cat: "autostart", msg: "Auto-start disabled, skipped")
            return []
        }

        guard !savedServers.isEmpty else {
            log.info("No saved servers to auto-start")
            return []
        }

        log.info("Starting sequential auto-start of \(savedServers.count) servers with \(self.settings.autoStartDelay)s delay")
        appLogger?.log(.info, cat: "autostart", msg: "Auto-start started", meta: ["count": .int(savedServers.count), "delay": .int(self.settings.autoStartDelay)])

        var started: [MCPServer] = []
        var toRemove: [SavedMCPServer] = []

        for (index, savedServer) in savedServers.enumerated() {
            // Find the server in registry
            guard let server = registry.registeredServers.first(where: { $0.id == savedServer.id }) else {
                log.warning("Saved server '\(savedServer.name)' (id: \(savedServer.id)) no longer in registry, removing from saved list")
                appLogger?.log(.warn, cat: "autostart", msg: "Server not found in registry", meta: ["name": .string(savedServer.name)])
                toRemove.append(savedServer)
                continue
            }

            do {
                log.info("Auto-starting server \(index + 1)/\(savedServers.count): '\(server.manifest.name)'")
                try await processManager.start(server)
                started.append(server)
                appLogger?.log(.info, cat: "autostart", msg: "Server started", meta: ["name": .string(server.manifest.name)])

                // Delay before starting next server (except last one)
                if index < savedServers.count - 1 {
                    try await Task.sleep(nanoseconds: UInt64(settings.autoStartDelay) * 1_000_000_000)
                }
            } catch {
                log.error("Failed to auto-start server '\(server.manifest.name)': \(error.localizedDescription)")
                appLogger?.log(.error, cat: "autostart", msg: "Failed to start server", meta: [
                    "name": .string(server.manifest.name),
                    "error": .string(error.localizedDescription)
                ])
                // Continue with next server
            }
        }

        // Remove servers that are no longer in registry
        if !toRemove.isEmpty {
            var remaining = savedServers
            remaining.removeAll { removed in toRemove.contains { $0.id == removed.id } }
            saveRunningServers(registry.registeredServers.filter { server in remaining.contains { $0.id == server.id } })
        }

        log.info("Auto-start complete: \(started.count)/\(savedServers.count) servers started")
        appLogger?.log(.info, cat: "autostart", msg: "Auto-start complete", meta: ["started": .int(started.count), "total": .int(savedServers.count)])

        return started
    }
}
