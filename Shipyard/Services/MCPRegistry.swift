import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "MCPRegistry")

/// Registry for discovering and managing registered MCP servers
@Observable @MainActor final class MCPRegistry {
    static let shipyardServerName = "shipyard"

    private(set) var registeredServers: [MCPServer] = []
    private(set) var manifestImportStatus: ManifestImportStatus = .pending(legacyCount: 0)
    private(set) var manifestDiscoveryReadOnly = false
    private let dependencyChecker = DependencyChecker()

    /// Discovery path — resolves dynamically from user home directory.
    private let discoveryPath: String

    /// App logger — injected from ShipyardApp
    var appLogger: AppLogger?

    init(discoveryPath: String = PathManager.shared.mcpDiscoveryRoot.path) {
        self.discoveryPath = discoveryPath
        log.info("MCPRegistry initialized")
    }

    func setManifestImportStatus(_ status: ManifestImportStatus) {
        manifestImportStatus = status
    }

    func setManifestDiscoveryReadOnly(_ readOnly: Bool) {
        manifestDiscoveryReadOnly = readOnly
    }

    /// Ensures the synthetic Shipyard server exists and remains in a running state.
    func ensureSyntheticShipyardServerRegistered() {
        if let existing = registeredServers.first(where: {
            $0.manifest.name.caseInsensitiveCompare(Self.shipyardServerName) == .orderedSame
        }) {
            existing.state = .running
            return
        }

        registeredServers.append(Self.makeSyntheticShipyardServer())
    }

    var sortedServers: [MCPServer] {
        registeredServers.sorted { lhs, rhs in
            let lhsRank = sourceSortRank(lhs.source)
            let rhsRank = sourceSortRank(rhs.source)
            if lhsRank != rhsRank {
                return lhsRank < rhsRank
            }

            return lhs.manifest.name.localizedCaseInsensitiveCompare(rhs.manifest.name) == .orderedAscending
        }
    }

    // MARK: - Discovery

    /// Discovers MCP servers by scanning for manifest.json files
    /// Scans for directories containing manifest.json and creates MCPServer instances
    func discover() async throws {
        guard !manifestDiscoveryReadOnly else {
            log.info("Manifest discovery is read-only after cutover; skipping active manifest registration")
            appLogger?.log(.info, cat: "registry", msg: "Manifest discovery skipped (read-only)")
            return
        }

        let profiler = StartupProfiler.shared
        profiler.begin("registry.discover")
        defer { profiler.end("registry.discover") }

        log.info("🔍 discover() called — scanning \(self.discoveryPath)")
        appLogger?.log(.info, cat: "registry", msg: "Discovery started")

        let fileManager = FileManager.default
        let rootURL = URL(fileURLWithPath: discoveryPath)

        guard fileManager.fileExists(atPath: discoveryPath) else {
            log.error("❌ Discovery path does not exist: \(self.discoveryPath)")
            appLogger?.log(.error, cat: "registry", msg: "Discovery path not found", meta: ["path": .string(discoveryPath)])
            throw RegistryError.discoveryPathNotFound
        }

        do {
            let contents = try fileManager.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles]
            )
            log.info("📂 Found \(contents.count) items in discovery path")

            var discovered: [MCPServer] = []

            for item in contents {
                let isDir = (try item.resourceValues(forKeys: [.isDirectoryKey])).isDirectory ?? false
                guard isDir else { continue }

                let manifestURL = item.appendingPathComponent("manifest.json")
                guard fileManager.fileExists(atPath: manifestURL.path) else { continue }

                do {
                    let manifest = try MCPManifest.load(from: item)
                    let server = MCPServer(manifest: manifest)
                    discovered.append(server)
                    log.info("✅ Loaded manifest: \(manifest.name) from \(item.lastPathComponent)")
                    appLogger?.log(.debug, cat: "registry", msg: "Loaded manifest: \(manifest.name)")
                } catch {
                    log.warning("⚠️ Failed to load manifest from \(item.lastPathComponent): \(error.localizedDescription)")
                }
            }

            log.info("📋 Discovered \(discovered.count) servers, existing \(self.registeredServers.count)")

            // Update registered servers (deduplicate by name)
            var existingNames = Set(registeredServers.map { $0.manifest.name })
            for server in discovered {
                if !existingNames.contains(server.manifest.name) {
                    registeredServers.append(server)
                    existingNames.insert(server.manifest.name)
                    log.info("➕ Registered: \(server.manifest.name)")
                }
            }

            // Check dependencies (Phase 4.4)
            for server in registeredServers where !server.dependenciesChecked {
                let results = await dependencyChecker.check(server.manifest)
                server.dependencyResults = results
                server.dependenciesChecked = true
                let unsatisfied = results.filter { !$0.satisfied }
                if unsatisfied.isEmpty {
                    log.info("✅ Dependencies OK for \(server.manifest.name)")
                } else {
                    for dep in unsatisfied {
                        log.warning("⚠️ \(server.manifest.name): \(dep.message)")
                    }
                }
            }

            log.info("✅ Discovery complete — \(self.registeredServers.count) servers total")
            appLogger?.log(.info, cat: "registry", msg: "Discovery complete", meta: ["count": .int(registeredServers.count)])

        } catch {
            log.error("❌ Discovery failed: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "registry", msg: "Discovery failed", meta: ["error": .string(error.localizedDescription)])
            throw RegistryError.discoveryFailed(error.localizedDescription)
        }
    }

    // MARK: - Server Management

    /// Registers a new server
    func register(_ server: MCPServer) throws {
        guard !registeredServers.contains(where: {
            $0.manifest.name.caseInsensitiveCompare(server.manifest.name) == .orderedSame
        }) else {
            throw RegistryError.serverAlreadyRegistered(server.manifest.name)
        }
        registeredServers.append(server)
    }

    /// Unregisters a server by ID
    func unregister(_ serverId: UUID) {
        registeredServers.removeAll { $0.id == serverId }
    }

    /// Gets a server by name
    func server(named name: String) -> MCPServer? {
        registeredServers.first { $0.manifest.name == name }
    }

    // MARK: - Auto-Discovery Rescan

    /// Performs an incremental rescan of the discovery path
    /// Handles adds, removals, and changes compared to the current registry
    /// This is called by DirectoryWatcher when filesystem changes are detected
    func rescan() async {
        guard !manifestDiscoveryReadOnly else {
            log.info("Manifest discovery is read-only after cutover; ignoring filesystem changes")
            appLogger?.log(.info, cat: "registry", msg: "Manifest rescan ignored (read-only)")
            return
        }

        log.info("🔄 rescan() called — performing incremental discovery")
        appLogger?.log(.info, cat: "registry", msg: "Rescan started")

        let fileManager = FileManager.default
        let rootURL = URL(fileURLWithPath: discoveryPath)

        guard fileManager.fileExists(atPath: discoveryPath) else {
            log.error("❌ Discovery path does not exist: \(self.discoveryPath)")
            appLogger?.log(.error, cat: "registry", msg: "Discovery path not found during rescan")
            return
        }

        do {
            // Scan current filesystem
            let contents = try fileManager.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles]
            )

            var discoveredByName: [String: (MCPServer, MCPManifest)] = [:]

            for item in contents {
                let isDir = (try item.resourceValues(forKeys: [.isDirectoryKey])).isDirectory ?? false
                guard isDir else { continue }

                let manifestURL = item.appendingPathComponent("manifest.json")
                guard fileManager.fileExists(atPath: manifestURL.path) else { continue }

                do {
                    let manifest = try MCPManifest.load(from: item)
                    let server = MCPServer(manifest: manifest)
                    discoveredByName[manifest.name] = (server, manifest)
                    log.debug("Found on disk: \(manifest.name)")
                } catch {
                    log.warning("⚠️ Failed to load manifest from \(item.lastPathComponent): \(error.localizedDescription)")
                }
            }

            // Build a map of currently registered servers by name
            var registeredByName: [String: MCPServer] = [:]
            for server in registeredServers {
                registeredByName[server.manifest.name] = server
            }

            // Handle NEW servers (discovered but not registered)
            for (name, (newServer, _)) in discoveredByName {
                if registeredByName[name] == nil {
                    registeredServers.append(newServer)
                    log.info("✅ NEW server discovered: \(name)")
                    appLogger?.log(.info, cat: "registry", msg: "New server discovered", meta: ["name": .string(name)])
                }
            }

            // Handle REMOVED servers (registered but not on disk)
            var toRemove: [MCPServer] = []
            for server in registeredServers where server.source == .manifest {
                let name = server.manifest.name
                if discoveredByName[name] == nil {
                    // Manifest no longer exists on disk
                    if server.state.isRunning {
                        // Server is running — mark orphaned instead of removing
                        server.isOrphaned = true
                        log.warning("⚠️ Server running but manifest removed: \(name) — marking orphaned")
                        appLogger?.log(.warn, cat: "registry", msg: "Server orphaned (manifest removed)", meta: ["name": .string(name)])
                    } else {
                        // Server is idle — remove it
                        toRemove.append(server)
                        log.info("🗑️ Removing idle server (manifest gone): \(name)")
                        appLogger?.log(.info, cat: "registry", msg: "Idle server removed (manifest gone)", meta: ["name": .string(name)])
                    }
                }
            }

            registeredServers.removeAll { server in
                toRemove.contains { $0.id == server.id }
            }

            // Handle CHANGED manifests (same name, but manifest content changed)
            var updatedServers: [MCPServer] = []
            for server in registeredServers where server.source == .manifest {
                let name = server.manifest.name
                if let (_, newManifest) = discoveredByName[name] {
                    // Compare manifests
                    if !manifestsEqual(server.manifest, newManifest) {
                        if server.state.isRunning {
                            // Server is running — flag for restart
                            server.configNeedsRestart = true
                            log.warning("⚠️ Manifest changed while running: \(name) — restart needed")
                            appLogger?.log(.warn, cat: "registry", msg: "Manifest changed (server running)", meta: ["name": .string(name), "action": .string("restart_needed")])
                        } else {
                            // Server is idle — create a new server with updated manifest
                            let newServer = MCPServer(manifest: newManifest)
                            updatedServers.append(newServer)
                            log.info("🔄 Manifest reloaded: \(name)")
                            appLogger?.log(.info, cat: "registry", msg: "Manifest reloaded", meta: ["name": .string(name)])
                        }
                    }
                }
            }

            // Replace idle servers with updated ones
            if !updatedServers.isEmpty {
                for updatedServer in updatedServers {
                    if let idx = registeredServers.firstIndex(where: { $0.manifest.name == updatedServer.manifest.name }) {
                        registeredServers[idx] = updatedServer
                    }
                }
            }

            log.info("✅ Rescan complete — \(self.registeredServers.count) servers total")
            appLogger?.log(.info, cat: "registry", msg: "Rescan complete", meta: ["count": .int(registeredServers.count)])

        } catch {
            log.error("❌ Rescan failed: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "registry", msg: "Rescan failed", meta: ["error": .string(error.localizedDescription)])
        }
    }

    /// Compare two manifests for equality
    /// Checks all essential fields that affect runtime behavior
    private func manifestsEqual(_ manifest1: MCPManifest, _ manifest2: MCPManifest) -> Bool {
        return manifest1.name == manifest2.name &&
               manifest1.version == manifest2.version &&
               manifest1.description == manifest2.description &&
               manifest1.transport == manifest2.transport &&
               manifest1.command == manifest2.command &&
               manifest1.args == manifest2.args &&
               manifest1.env == manifest2.env &&
               manifest1.env_secret_keys == manifest2.env_secret_keys
    }

    // MARK: - Config Loading (SPEC-019)

    /// Loads MCPs from the centralized mcps.json path.
    /// Called once on startup after discover()
    func loadConfig(
        from path: String = MCPConfig.defaultPath,
        migrationLogPath: String = PathManager.shared.manifestMigrationLogFile.path
    ) async {
        let profiler = StartupProfiler.shared
        profiler.begin("registry.loadConfig")
        defer { profiler.end("registry.loadConfig") }

        log.info("📂 loadConfig() called — loading config from \(path)")
        appLogger?.log(.info, cat: "registry", msg: "Config loading started")

        do {
            // Load MCPConfig from default path
            let config = try MCPConfig.loadOrCreateDefault(at: path)
            log.info("✅ Loaded config with \(config.mcpServers.count) entries")

            // Validate config
            let validationErrors = config.validate()
            if !validationErrors.isEmpty {
                for error in validationErrors {
                    log.warning("⚠️ Config validation: \(error)")
                    appLogger?.log(.warn, cat: "registry", msg: "Config validation error", meta: ["error": .string(error)])
                }
            }

            persistMigrationLog(from: config, to: migrationLogPath)

            // Track config-sourced servers by name
            var configServersByName: [String: MCPServer] = [:]
            let registeredByName = Dictionary(uniqueKeysWithValues: registeredServers.map { ($0.manifest.name.lowercased(), $0) })

            // Process each config entry
            for (name, entry) in config.mcpServers {
                let server = makeConfigServer(name: name, entry: entry)

                // Handle name collisions (case-insensitive)
                if registeredByName[name.lowercased()] != nil {
                    // Check if config entry has override flag
                    if entry.override ?? false {
                        // Config overrides manifest
                        log.info("⚙️ Config override: config entry '\(name)' takes priority over manifest")
                        appLogger?.log(.info, cat: "registry", msg: "Config override applied", meta: ["name": .string(name)])
                        configServersByName[name] = server
                    } else {
                        // Manifest wins (default behavior)
                        log.warning("⚠️ Name collision (case-insensitive): '\(name)' exists in manifest — manifest wins")
                        appLogger?.log(.warn, cat: "registry", msg: "Name collision (manifest wins)", meta: ["name": .string(name)])
                        // Don't add config version; manifest already registered
                    }
                } else {
                    // No collision
                    configServersByName[name] = server
                }
            }

            // Register new config-sourced servers and apply overrides
            for (name, server) in configServersByName {
                if let existingIdx = registeredServers.firstIndex(where: { $0.manifest.name == name }) {
                    // Replace with override
                    registeredServers[existingIdx] = server
                    log.info("🔄 Replaced manifest server with config override: \(name)")
                } else {
                    // New config server
                    registeredServers.append(server)
                    log.info("➕ Registered config server: \(name)")
                }
            }

            log.info("✅ Config loading complete — \(configServersByName.count) config-sourced servers registered")
            appLogger?.log(.info, cat: "registry", msg: "Config loading complete", meta: ["count": .int(configServersByName.count)])

        } catch {
            log.error("❌ Config loading failed: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "registry", msg: "Config loading failed", meta: ["error": .string(error.localizedDescription)])
            // Don't throw — let discovery continue even if config load fails
        }
    }

    /// Reloads config — called by ConfigFileWatcher on change
    /// Diffs against current config-sourced servers, adds/removes/updates
    func reloadConfig(
        from path: String = MCPConfig.defaultPath,
        migrationLogPath: String = PathManager.shared.manifestMigrationLogFile.path
    ) async {
        log.info("🔄 reloadConfig() called — reloading config from \(path)")
        appLogger?.log(.info, cat: "registry", msg: "Config reload started")

        do {
            // Load new config
            let newConfig = try MCPConfig.loadOrCreateDefault(at: path)
            log.info("✅ Reloaded config with \(newConfig.mcpServers.count) entries")

            // Validate config
            let validationErrors = newConfig.validate()
            if !validationErrors.isEmpty {
                for error in validationErrors {
                    log.warning("⚠️ Config validation: \(error)")
                    appLogger?.log(.warn, cat: "registry", msg: "Config validation error on reload", meta: ["error": .string(error)])
                }
            }

            persistMigrationLog(from: newConfig, to: migrationLogPath)

            // Identify current config-sourced servers
            let currentConfigServers = registeredServers.filter { $0.source == .config }
            let currentByName = Dictionary(uniqueKeysWithValues: currentConfigServers.map { ($0.manifest.name, $0) })

            // Build new config-sourced servers
            var newConfigByName: [String: MCPServer] = [:]
            let manifestServersByName = Dictionary(uniqueKeysWithValues: registeredServers.filter { $0.source == .manifest }.map { ($0.manifest.name.lowercased(), $0) })

            for (name, entry) in newConfig.mcpServers {
                let server = makeConfigServer(name: name, entry: entry)

                // Handle name collisions with manifest servers (case-insensitive)
                if manifestServersByName[name.lowercased()] != nil {
                    if entry.override ?? false {
                        // Config overrides manifest
                        log.info("⚙️ Config override: config entry '\(name)' replaces manifest server")
                        appLogger?.log(.info, cat: "registry", msg: "Config override on reload", meta: ["name": .string(name)])
                        newConfigByName[name] = server
                    } else {
                        // Manifest wins
                        log.warning("⚠️ Name collision (case-insensitive) on reload: '\(name)' — manifest still wins")
                        // Don't add config version
                    }
                } else {
                    newConfigByName[name] = server
                }
            }

            // Handle REMOVED servers (in current config but not in new config)
            for (name, currentServer) in currentByName {
                if newConfigByName[name] == nil {
                    // Server no longer in config
                    if currentServer.state.isRunning {
                        // Server is running — keep it visible until the user stops it
                        currentServer.isPendingConfigRemoval = true
                        currentServer.configNeedsRestart = false
                        log.warning("⚠️ Config server removed while running: \(name) — pending removal")
                        appLogger?.log(.warn, cat: "registry", msg: "Config server removed (running)", meta: ["name": .string(name)])
                    } else {
                        // Server is idle — remove it
                        registeredServers.removeAll { $0.id == currentServer.id }
                        log.info("🗑️ Config server removed: \(name)")
                        appLogger?.log(.info, cat: "registry", msg: "Config server removed", meta: ["name": .string(name)])
                    }
                }
            }

            // Handle NEW servers (in new config but not in current config)
            for (name, newServer) in newConfigByName {
                if currentByName[name] == nil {
                    registeredServers.append(newServer)
                    log.info("✅ NEW config server: \(name)")
                    appLogger?.log(.info, cat: "registry", msg: "New config server added", meta: ["name": .string(name)])
                }
            }

            // Handle CHANGED servers (same name, but config changed)
            for (name, currentServer) in currentByName {
                if let newServer = newConfigByName[name] {
                    currentServer.isPendingConfigRemoval = false

                    // Compare manifests to detect changes
                    if !configServersEqual(currentServer, newServer) {
                        if currentServer.state.isRunning {
                            // Server is running — flag for restart
                            currentServer.configNeedsRestart = true
                            log.warning("⚠️ Config changed while running: \(name) — restart needed")
                            appLogger?.log(.warn, cat: "registry", msg: "Config changed (server running)", meta: ["name": .string(name)])
                        } else {
                            // Server is idle — replace it
                            if let idx = registeredServers.firstIndex(where: { $0.id == currentServer.id }) {
                                registeredServers[idx] = newServer
                                log.info("🔄 Config server updated: \(name)")
                                appLogger?.log(.info, cat: "registry", msg: "Config server updated", meta: ["name": .string(name)])
                            }
                        }
                    }
                }
            }

            // Handle OVERRIDE changes (config entry changed from/to override)
            for (name, newServer) in newConfigByName {
                if currentByName[name] != nil,
                   let existingManifestIdx = registeredServers.firstIndex(where: { $0.manifest.name == name && $0.source == .manifest }) {
                    registeredServers[existingManifestIdx] = newServer
                    log.info("⚙️ Config override updated: \(name)")
                }
            }

            log.info("✅ Config reload complete")
            appLogger?.log(.info, cat: "registry", msg: "Config reload complete")

        } catch {
            log.error("❌ Config reload failed: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "registry", msg: "Config reload failed", meta: ["error": .string(error.localizedDescription)])
            // Don't throw — keep existing servers, allow user to fix config
        }
    }

    /// Removes an idle config-backed server that was already deleted from mcps.json.
    func removeServerIfPendingConfigRemoval(_ server: MCPServer) {
        guard server.source == .config, server.isPendingConfigRemoval, !server.state.isRunning else {
            return
        }

        unregister(server.id)
        log.info("🗑️ Removed pending config server after stop: \(server.manifest.name)")
        appLogger?.log(.info, cat: "registry", msg: "Pending config server removed after stop", meta: ["name": .string(server.manifest.name)])
    }

    private func makeConfigServer(name: String, entry: MCPConfig.ServerEntry) -> MCPServer {
        let transport = transport(for: entry.transport)
        let transportString = entry.transport ?? "stdio"

        var manifest = MCPManifest(
            name: name,
            version: "config",
            description: entry.cwd.map { "cwd: \($0)" } ?? "",
            transport: transportString,
            command: entry.command ?? "",
            args: entry.args ?? [],
            env: entry.env,
            env_secret_keys: entry.envSecretKeys,
            dependencies: nil,
            health_check: nil,
            logging: nil,
            install: nil
        )

        if let cwd = entry.cwd {
            manifest.setRootDirectory(URL(fileURLWithPath: (cwd as NSString).expandingTildeInPath))
        } else if let command = entry.command, command.hasPrefix("/") {
            manifest.setRootDirectory(URL(fileURLWithPath: command).deletingLastPathComponent())
        } else {
            manifest.setRootDirectory(URL(fileURLWithPath: NSHomeDirectory()))
        }

        let server = MCPServer(manifest: manifest, source: .config, transport: transport)
        server.configCwd = entry.cwd
        server.configHTTPEndpoint = entry.url
        server.configTimeout = entry.timeout
        server.disabled = entry.disabled ?? false
        server.configEnvSecretKeys = entry.envSecretKeys
        server.configHeaderSecretKeys = entry.headersSecretKeys
        server.configHeaders = entry.headers
        server.migratedFrom = entry.migratedFrom
        return server
    }

    private func persistMigrationLog(from config: MCPConfig, to path: String) {
        var entries: [String: MCPConfig.MigrationLogEntry] = [:]
        for (name, entry) in config.mcpServers {
            guard let logEntry = entry.migrationLogEntry(named: name) else {
                continue
            }
            entries[name] = logEntry
        }

        do {
            let migrationLog = MCPConfig.MigrationLog(entries: entries)
            try migrationLog.save(to: path)
            if !entries.isEmpty {
                appLogger?.log(.info, cat: "registry", msg: "Migration log updated", meta: ["count": .int(entries.count)])
            }
        } catch {
            log.warning("⚠️ Failed to persist migration log: \(error.localizedDescription)")
            appLogger?.log(.warn, cat: "registry", msg: "Migration log update failed", meta: ["error": .string(error.localizedDescription)])
        }
    }

    private func transport(for transport: String?) -> MCPTransport {
        switch transport {
        case "streamable-http":
            return .streamableHTTP
        case "sse":
            return .sse
        default:
            return .stdio
        }
    }

    private func configServersEqual(_ lhs: MCPServer, _ rhs: MCPServer) -> Bool {
        manifestsEqual(lhs.manifest, rhs.manifest) &&
        lhs.transport == rhs.transport &&
        lhs.configCwd == rhs.configCwd &&
        lhs.configHTTPEndpoint == rhs.configHTTPEndpoint &&
        lhs.configTimeout == rhs.configTimeout &&
        lhs.disabled == rhs.disabled &&
        lhs.configEnvSecretKeys == rhs.configEnvSecretKeys &&
        lhs.configHeaderSecretKeys == rhs.configHeaderSecretKeys &&
        lhs.configHeaders == rhs.configHeaders
    }

    private func sourceSortRank(_ source: MCPSource) -> Int {
        switch source {
        case .synthetic:
            return 0
        case .manifest:
            return 1
        case .config:
            return 2
        }
    }

    private static func makeSyntheticShipyardServer() -> MCPServer {
        var manifest = MCPManifest(
            name: shipyardServerName,
            version: "builtin",
            description: "Shipyard built-in gateway server",
            transport: MCPTransport.stdio.rawValue,
            command: "builtin",
            args: [],
            env: nil,
            env_secret_keys: nil,
            dependencies: nil,
            health_check: nil,
            logging: nil,
            install: nil
        )
        manifest.setRootDirectory(URL(fileURLWithPath: NSHomeDirectory()))

        let server = MCPServer(manifest: manifest, source: .synthetic, transport: .stdio)
        server.state = .running
        server.healthStatus = .healthy
        server.dependenciesChecked = true
        return server
    }
}

// MARK: - Error Types

enum RegistryError: LocalizedError, Sendable {
    case discoveryPathNotFound
    case discoveryFailed(String)
    case serverAlreadyRegistered(String)
    case configLoadFailed(String)

    var errorDescription: String? {
        switch self {
        case .discoveryPathNotFound:
            return L10n.string("error.registry.discoveryPathNotFound")
        case .discoveryFailed(let reason):
            return L10n.format("error.registry.discoveryFailed", reason)
        case .serverAlreadyRegistered(let name):
            return L10n.format("error.registry.serverAlreadyRegistered", name)
        case .configLoadFailed(let reason):
            return L10n.format("error.registry.configLoadFailed", reason)
        }
    }
}
