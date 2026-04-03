import Foundation
import Darwin
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ProcessManager")

/// Common paths not present in GUI app environments
private let extraPATH = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin"

/// Manages lifecycle of MCP server processes
@Observable @MainActor final class ProcessManager {
    private var processDict: [UUID: Foundation.Process] = [:]
    private var stdinPipes: [UUID: Pipe] = [:]
    private var stderrTasks: [UUID: Task<Void, Never>] = [:]
    private var stdoutTasks: [UUID: Task<Void, Never>] = [:]
    private var monitoringTasks: [UUID: Task<Void, Never>] = [:]
    private var bridges: [UUID: MCPBridge] = [:]

    /// Log file writer — persists stderr to disk with rotation (Phase 2)
    let logFileWriter = LogFileWriter()

    /// Keychain manager — resolves env_secret_keys at process start (Phase 2)
    var keychainManager: KeychainManager?

    /// App logger — injected from ShipyardApp
    var appLogger: AppLogger?

    /// Registry reference for lifecycle-driven cleanup of config-backed servers.
    weak var registry: MCPRegistry?

    /// Auto-start manager for persisting currently running servers.
    weak var autoStartManager: AutoStartManager?

    /// Parser for MCP protocol notifications (Phase 4.1)
    private let notificationParser = MCPNotificationParser()

    /// HTTP bridges for HTTP transports (streamable-http and sse)
    private var httpBridges: [UUID: any BridgeProtocol] = [:]

    init() {
        log.info("ProcessManager initialized")
    }

    /// Get any bridge (stdio or HTTP) for a server (nil if not running)
    func bridge(for server: MCPServer) -> MCPBridge? {
        bridges[server.id]
    }

    /// Get an HTTP bridge for an HTTP server (nil if not connected)
    func httpBridge(for server: MCPServer) -> (any BridgeProtocol)? {
        httpBridges[server.id]
    }

    /// Get a transport-agnostic bridge for gateway calls
    func bridgeProtocol(for server: MCPServer) -> (any BridgeProtocol)? {
        if server.transport == .streamableHTTP || server.transport == .sse {
            return httpBridges[server.id]
        } else {
            return bridges[server.id]
        }
    }

    // MARK: - Process Lifecycle

    /// Starts the MCP process for a given server
    /// - Parameters:
    ///   - server: The server instance to start
    /// - Throws: ProcessManagerError if the process fails to start
    func start(_ server: MCPServer) async throws {
        let profiler = StartupProfiler.shared
        let totalStartAbs = CFAbsoluteTimeGetCurrent()
        var spawnDurationMs: Double = 0
        var handshakeDurationMs: Double = 0

        let manifest = server.manifest
        log.info("▶️ start() called for '\(manifest.name)' from \(server.source.rawValue)")
        var startLogMetadata: [String: AnyCodableValue] = ["source": .string(server.source.rawValue)]
        if let migratedFrom = server.migratedFrom {
            startLogMetadata["migrated_from"] = .string(migratedFrom)
        }
        appLogger?.log(.info, cat: "process", msg: "Starting \(manifest.name)", meta: startLogMetadata)

        guard let rootDir = manifest.rootDirectory else {
            log.error("❌ No rootDirectory on manifest for '\(manifest.name)'")
            appLogger?.log(.error, cat: "process", msg: "No rootDirectory for \(manifest.name)")
            throw ProcessManagerError.noRootDirectory
        }
        log.info("  rootDir: \(rootDir.path)")

        server.state = .starting
        log.info("  state → .starting")

        do {
            let process = Foundation.Process()
            // Use /usr/bin/env to resolve commands (e.g., "python3") via PATH
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = [manifest.command] + manifest.args
            process.currentDirectoryURL = rootDir
            log.info("  exec: /usr/bin/env \(manifest.command) \(manifest.args.joined(separator: " "))")

            // Set up environment: merge manifest env with process environment
            // GUI apps have a minimal PATH — inject common locations (homebrew etc.)
            var env = ProcessInfo.processInfo.environment
            let currentPATH = env["PATH"] ?? "/usr/bin:/bin"
            env["PATH"] = "\(extraPATH):\(currentPATH)"
            if let manifestEnv = manifest.env {
                env.merge(manifestEnv) { _, new in new }
            }
            // Resolve secrets from Keychain (Phase 2)
            if let km = keychainManager {
                let secrets = km.resolveSecrets(for: manifest)
                env.merge(secrets) { _, new in new }
                if !secrets.isEmpty {
                    log.info("  injected \(secrets.count) secret(s) from Keychain")
                }

                // Also resolve config-sourced env secrets (R26)
                if let configSecretKeys = server.configEnvSecretKeys, !configSecretKeys.isEmpty {
                    var configSecrets: [String: String] = [:]
                    for key in configSecretKeys {
                        if let value = km.load(serverName: manifest.name, key: key) {
                            configSecrets[key] = value
                        } else {
                            log.warning("  Secret key '\(key)' not found in Keychain for '\(manifest.name)'")
                        }
                    }
                    env.merge(configSecrets) { _, new in new }
                    if !configSecrets.isEmpty {
                        log.info("  injected \(configSecrets.count) config secret(s) from Keychain")
                    }
                }
            }
            process.environment = env
            log.info("  PATH: \(env["PATH"] ?? "(nil)")")

            // Set up stdin pipe (keeps server alive; no writes yet — Phase 2 will add MCP protocol)
            let stdinPipe = Pipe()
            process.standardInput = stdinPipe

            // Set up stdout pipe (MCP JSON-RPC responses; not used in Phase 1)
            let stdoutPipe = Pipe()
            process.standardOutput = stdoutPipe

            // Set up stderr pipe (server logs)
            let stderrPipe = Pipe()
            process.standardError = stderrPipe

            // Launch process
            log.info("  launching process...")
            let spawnStartAbs = CFAbsoluteTimeGetCurrent()
            try process.run()
            let spawnEndAbs = CFAbsoluteTimeGetCurrent()
            spawnDurationMs = max(0, (spawnEndAbs - spawnStartAbs) * 1000)
            log.info("  ✅ process launched, PID=\(process.processIdentifier)")
            
            // Track start time for duration calculations
            server.startTime = Date()
            
            let startMetadata = LogMetadataHelper.processStartMetadata(
                mcpName: manifest.name,
                command: manifest.command,
                arguments: manifest.args,
                pid: Int(process.processIdentifier),
                version: manifest.version,
                stateTransition: "idle → starting"
            )
            appLogger?.log(.info, cat: "lifecycle", msg: "Process started: \(manifest.name)", meta: startMetadata)

            // Store process and pipe references
            processDict[server.id] = process
            stdinPipes[server.id] = stdinPipe

            // Create MCPBridge for gateway communication
            let bridge = MCPBridge(mcpName: manifest.name, stdinPipe: stdinPipe)
            bridge.onNotification = { [weak self] line in
                guard let self else { return }
                if let entry = self.notificationParser.parse(line: line) {
                    server.appendLog(entry)
                    self.logFileWriter.write(entry, serverName: server.manifest.name)
                }
            }
            bridge.onLog = { [weak self] message, level in
                let entry = LogEntry(timestamp: Date(), message: message, level: level, source: .mcp)
                server.appendLog(entry)
                self?.logFileWriter.write(entry, serverName: server.manifest.name)
            }
            bridges[server.id] = bridge
            log.info("  MCPBridge created for '\(manifest.name)'")

            // Start stderr capture in a background task
            let stderrTask = Task {
                await self.captureStderr(from: stderrPipe, for: server)
            }
            stderrTasks[server.id] = stderrTask
            log.info("  stderr capture task started")

            // Start stdout capture for MCP notifications (Phase 4.1)
            let stdoutTask = Task {
                await self.captureStdout(from: stdoutPipe, for: server)
            }
            stdoutTasks[server.id] = stdoutTask
            log.info("  stdout capture task started (MCP notifications)")

            // Perform MCP protocol initialization handshake
            let handshakeStartAbs = CFAbsoluteTimeGetCurrent()
            do {
                _ = try await bridge.initialize()
                handshakeDurationMs = max(0, (CFAbsoluteTimeGetCurrent() - handshakeStartAbs) * 1000)
                log.info("  ✅ MCP handshake complete for '\(manifest.name)'")
            } catch {
                handshakeDurationMs = max(0, (CFAbsoluteTimeGetCurrent() - handshakeStartAbs) * 1000)
                log.warning("  ⚠️ MCP handshake failed for '\(manifest.name)': \(error.localizedDescription) — server may not support all features")
            }

            server.state = .running
            log.info("  state → .running")
            persistRunningState()

            let totalDurationMs = max(0, (CFAbsoluteTimeGetCurrent() - totalStartAbs) * 1000)
            profiler.recordServerStartup(
                name: manifest.name,
                spawnMs: spawnDurationMs,
                handshakeMs: handshakeDurationMs,
                totalMs: totalDurationMs
            )

            // Start resource monitoring (Phase 4.3)
            self.startMonitoring(for: server, pid: process.processIdentifier)
            log.info("  resource monitoring started")

        } catch {
            log.error("❌ start() failed for '\(manifest.name)': \(error.localizedDescription)")
            appLogger?.log(.error, cat: "process", msg: "Failed to start \(manifest.name)", meta: ["error": .string(error.localizedDescription)])
            server.state = .error("Failed to start: \(error.localizedDescription)")
            let totalDurationMs = max(0, (CFAbsoluteTimeGetCurrent() - totalStartAbs) * 1000)
            profiler.recordServerStartup(
                name: manifest.name,
                spawnMs: spawnDurationMs,
                handshakeMs: handshakeDurationMs,
                totalMs: totalDurationMs
            )
            throw ProcessManagerError.startFailed(error.localizedDescription)
        }
    }

    /// Stops the MCP process for a given server gracefully
    /// - Parameters:
    ///   - server: The server instance to stop
    func stop(_ server: MCPServer) async {
        log.info("⏹️ stop() called for '\(server.manifest.name)', state=\(String(describing: server.state))")
        appLogger?.log(.info, cat: "process", msg: "Stopping \(server.manifest.name)")

        guard case .running = server.state else {
            log.warning("  skip — not running (state=\(String(describing: server.state)))")
            return
        }

        server.state = .stopping
        log.info("  state → .stopping")

        // Cancel MCPBridge pending requests
        if let bridge = bridges[server.id] {
            bridge.cancelAll()
            bridges.removeValue(forKey: server.id)
            log.info("  MCPBridge destroyed")
        }

        // Close stdin pipe (sends EOF to server)
        if let stdinPipe = stdinPipes[server.id] {
            stdinPipe.fileHandleForWriting.closeFile()
            stdinPipes.removeValue(forKey: server.id)
            log.info("  stdin pipe closed (EOF sent)")
        }

        // Cancel stderr reading task
        if let stderrTask = stderrTasks[server.id] {
            stderrTask.cancel()
            stderrTasks.removeValue(forKey: server.id)
            log.info("  stderr task cancelled")
        }

        // Cancel stdout reading task
        if let stdoutTask = stdoutTasks[server.id] {
            stdoutTask.cancel()
            stdoutTasks.removeValue(forKey: server.id)
            log.info("  stdout task cancelled")
        }

        // Cancel resource monitoring task
        if let monitoringTask = monitoringTasks[server.id] {
            monitoringTask.cancel()
            monitoringTasks.removeValue(forKey: server.id)
            log.info("  monitoring task cancelled")
        }

        // Clear process stats
        server.processStats = nil

        guard let process = processDict[server.id] else {
            log.warning("  no process found — setting idle")
            server.state = .idle
            persistRunningState()
            registry?.removeServerIfPendingConfigRemoval(server)
            return
        }

        // Send SIGTERM
        let pid = process.processIdentifier
        let startTime = server.startTime ?? Date()
        process.terminate()
        log.info("  SIGTERM sent to PID=\(pid)")

        // Wait up to 5 seconds for graceful shutdown
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if !process.isRunning {
                processDict.removeValue(forKey: server.id)
                server.state = .idle
                log.info("  ✅ process exited gracefully, state → .idle")
                persistRunningState()
                
                let durationMs = Int(Date().timeIntervalSince(startTime) * 1000)
                let stopMetadata = LogMetadataHelper.processStopMetadata(
                    mcpName: server.manifest.name,
                    pid: Int(pid),
                    exitCode: Int(process.terminationStatus),
                    durationMs: durationMs,
                    stateTransition: "running → idle"
                )
                appLogger?.log(.info, cat: "lifecycle", msg: "Process stopped: \(server.manifest.name)", meta: stopMetadata)
                registry?.removeServerIfPendingConfigRemoval(server)
                return
            }
            try? await Task.sleep(nanoseconds: 100_000_000) // 0.1s
        }

        // Force kill with SIGKILL
        if process.isRunning {
            kill(pid, SIGKILL)
            _ = waitpid(pid, nil, 0)
            log.warning("  ⚠️ SIGKILL sent to PID=\(pid)")
            appLogger?.log(.warn, cat: "process", msg: "Force-killed \(server.manifest.name)", meta: ["pid": .int(Int(pid))])
        }

        processDict.removeValue(forKey: server.id)
        server.state = .idle
        log.info("  state → .idle")
        persistRunningState()
        registry?.removeServerIfPendingConfigRemoval(server)
    }

    /// Restarts the MCP process
    /// - Parameters:
    ///   - server: The server instance to restart
    /// - Throws: ProcessManagerError if restart fails
    func restart(_ server: MCPServer) async throws {
        guard !server.isPendingConfigRemoval else {
            throw ProcessManagerError.stopFailed("Server was removed from config. Stop it to finish removal or restore it in mcps.json.")
        }

        appLogger?.log(.info, cat: "process", msg: "Restarting \(server.manifest.name)")
        await stop(server)
        try await start(server)
    }

    /// Checks if a process is currently running
    /// - Parameters:
    ///   - serverId: The UUID of the server
    /// - Returns: true if the process is running, false otherwise
    func isProcessRunning(_ serverId: UUID) -> Bool {
        guard let process = processDict[serverId] else {
            return false
        }
        return process.isRunning
    }

    /// Sync servers from registry (placeholder for future synchronization)
    func syncServers(from registry: MCPRegistry) async {
        // Future: could register servers here if needed
        // For now, this is a placeholder method called from ShipyardApp
    }

    /// Persist the currently running server set for crash-safe auto-start restore.
    private func persistRunningState() {
        guard let registry, let autoStartManager else { return }
        let running = registry.registeredServers.filter { $0.state.isRunning }
        autoStartManager.saveRunningServers(running)
    }

    // MARK: - Private Helpers

    /// Creates an AsyncStream from a Pipe that yields chunks of data
    private func pipeStream(from pipe: Pipe) -> AsyncStream<String> {
        AsyncStream { continuation in
            pipe.fileHandleForReading.readabilityHandler = { handle in
                let data = handle.availableData
                if data.isEmpty {
                    continuation.finish()
                    return
                }
                if let str = String(data: data, encoding: .utf8) {
                    continuation.yield(str)
                }
            }
            continuation.onTermination = { _ in
                pipe.fileHandleForReading.readabilityHandler = nil
            }
        }
    }

    /// Captures stderr from a server process and logs lines to the server
    /// - Parameters:
    ///   - pipe: The Pipe connected to the process's stderr
    ///   - server: The MCPServer to append logs to
    private func captureStderr(from pipe: Pipe, for server: MCPServer) async {
        log.info("📬 captureStderr started for '\(server.manifest.name)'")
        let stream = pipeStream(from: pipe)
        var lineBuffer = ""

        for await chunk in stream {
            lineBuffer.append(chunk)

            // Split on newlines and process complete lines
            let lines = lineBuffer.split(separator: "\n", omittingEmptySubsequences: false)

            // Keep the last incomplete line in the buffer
            if lineBuffer.hasSuffix("\n") {
                // All lines are complete, process them all
                for line in lines {
                    if !line.isEmpty {
                        logLine(String(line), to: server)
                    }
                }
                lineBuffer = ""
            } else {
                // Last element is incomplete, keep it in buffer
                if lines.count > 1 {
                    for line in lines.dropLast() {
                        if !line.isEmpty {
                            logLine(String(line), to: server)
                        }
                    }
                    lineBuffer = String(lines.last ?? "")
                }
            }
        }

        // Log any remaining content in the buffer
        if !lineBuffer.isEmpty {
            logLine(lineBuffer, to: server)
        }
        log.info("📬 captureStderr ended for '\(server.manifest.name)'")
    }

    /// Logs a line to the server on the main thread
    /// - Parameters:
    ///   - line: The line to log
    ///   - server: The server to log to
    private func logLine(_ line: String, to server: MCPServer) {
        let entry = LogEntry(timestamp: Date(), message: line)
        server.appendLog(entry)
        // Persist to disk (Phase 2)
        logFileWriter.write(entry, serverName: server.manifest.name)
    }

    /// Captures stdout from a server process, parses MCP notifications (Phase 4.1)
    /// - Parameters:
    ///   - pipe: The Pipe connected to the process's stdout
    ///   - server: The MCPServer to append logs to
    private func captureStdout(from pipe: Pipe, for server: MCPServer) async {
        log.info("📡 captureStdout started for '\(server.manifest.name)'")
        let stream = pipeStream(from: pipe)
        var lineBuffer = ""

        for await chunk in stream {
            lineBuffer.append(chunk)
            let lines = lineBuffer.split(separator: "\n", omittingEmptySubsequences: false)

            if lineBuffer.hasSuffix("\n") {
                for line in lines {
                    if !line.isEmpty {
                        let lineStr = String(line)
                        let bridge = self.bridges[server.id]
                        let consumed = bridge?.routeStdoutLine(lineStr) ?? false
                        
                        if !consumed {
                            // Fall back to notification parser
                            if let entry = notificationParser.parse(line: lineStr) {
                                server.appendLog(entry)
                                logFileWriter.write(entry, serverName: server.manifest.name)
                            }
                        }
                        // Non-notification JSON-RPC messages are silently ignored
                    }
                }
                lineBuffer = ""
            } else {
                if lines.count > 1 {
                    for line in lines.dropLast() {
                        if !line.isEmpty {
                            let lineStr = String(line)
                            let bridge = self.bridges[server.id]
                            let consumed = bridge?.routeStdoutLine(lineStr) ?? false
                            
                            if !consumed {
                                if let entry = notificationParser.parse(line: lineStr) {
                                    server.appendLog(entry)
                                    logFileWriter.write(entry, serverName: server.manifest.name)
                                }
                            }
                        }
                    }
                    lineBuffer = String(lines.last ?? "")
                }
            }
        }

        // Handle remaining buffer
        if !lineBuffer.isEmpty {
            let bridge = self.bridges[server.id]
            let consumed = bridge?.routeStdoutLine(lineBuffer) ?? false
            
            if !consumed {
                if let entry = notificationParser.parse(line: lineBuffer) {
                    server.appendLog(entry)
                    logFileWriter.write(entry, serverName: server.manifest.name)
                }
            }
        }
        log.info("📡 captureStdout ended for '\(server.manifest.name)'")
    }

    // MARK: - Resource Monitoring (Phase 4.3)

    /// Starts periodic monitoring for a running server process
    private func startMonitoring(for server: MCPServer, pid: Int32) {
        let task = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(3))
                guard !Task.isCancelled else { break }

                // Sample on a background thread
                let stats = await Task.detached {
                    Self.sampleStats(pid: pid)
                }.value

                server.processStats = stats
            }
        }
        monitoringTasks[server.id] = task
    }

    /// Samples resource stats for a PID (runs off main actor)
    nonisolated private static func sampleStats(pid: Int32) -> ProcessStats? {
        // Memory via proc_pid_rusage
        var usage = rusage_info_v4()
        let result = withUnsafeMutablePointer(to: &usage) { ptr in
            ptr.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { rusagePtr in
                proc_pid_rusage(pid, RUSAGE_INFO_V4, rusagePtr)
            }
        }
        guard result == 0 else { return nil }
        let memoryMB = Double(usage.ri_phys_footprint) / (1024.0 * 1024.0)

        // CPU via ps
        let task = Foundation.Process()
        task.executableURL = URL(fileURLWithPath: "/bin/ps")
        task.arguments = ["-p", "\(pid)", "-o", "%cpu="]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        do {
            try task.run()
            task.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let cpuStr = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "0"
            let cpu = Double(cpuStr) ?? 0.0
            return ProcessStats(pid: pid, cpuPercent: cpu, memoryMB: memoryMB, timestamp: Date())
        } catch {
            return ProcessStats(pid: pid, cpuPercent: 0, memoryMB: memoryMB, timestamp: Date())
        }
    }

    // MARK: - HTTP Bridge Management

    /// Connect to an HTTP MCP server.
    /// Creates an HTTPBridge, calls initialize(), and updates server state.
    func connectHTTP(_ server: MCPServer) async throws {
        log.info("▶️ connectHTTP() called for '\(server.manifest.name)'")
        appLogger?.log(.info, cat: "http", msg: "Connecting to \(server.manifest.name)")

        // Get endpoint URL from config
        guard let urlString = server.configHTTPEndpoint else {
            log.error("❌ No endpoint URL for HTTP MCP '\(server.manifest.name)'")
            throw ProcessManagerError.startFailed("No endpoint URL configured for HTTP transport")
        }

        guard let endpointURL = URL(string: urlString) else {
            log.error("❌ Invalid endpoint URL for '\(server.manifest.name)': \(urlString)")
            throw ProcessManagerError.startFailed("Invalid endpoint URL: \(urlString)")
        }

        server.state = .starting
        log.info("  state → .starting")

        do {
            let timeout: TimeInterval = server.configTimeout.map(TimeInterval.init) ?? 30

            // Resolve headers with secrets (R26)
            var headers = server.configHeaders ?? [:]
            if let headerSecretKeys = server.configHeaderSecretKeys, !headerSecretKeys.isEmpty,
               let km = keychainManager {
                for key in headerSecretKeys {
                    if let value = km.load(serverName: server.manifest.name, key: key) {
                        headers[key] = value
                        log.info("  Resolved header secret key '\(key)' from Keychain")
                    } else {
                        log.warning("  Header secret key '\(key)' not found in Keychain for '\(server.manifest.name)'")
                    }
                }
            }

            // Create appropriate bridge based on transport type
            let bridge: any BridgeProtocol
            if server.transport == .sse {
                bridge = SSEBridge(
                    mcpName: server.manifest.name,
                    endpointURL: endpointURL,
                    customHeaders: headers,
                    timeout: timeout
                )
                log.debug("  Created SSE bridge for '\(server.manifest.name)'")
            } else {
                bridge = HTTPBridge(
                    mcpName: server.manifest.name,
                    endpointURL: endpointURL,
                    customHeaders: headers,
                    timeout: timeout
                )
                log.debug("  Created Streamable HTTP bridge for '\(server.manifest.name)'")
            }

            // Initialize the bridge
            let initResponse = try await bridge.initialize()
            log.info("  ✅ Bridge initialized for '\(server.manifest.name)'")
            log.debug("  init response: \(initResponse)")

            httpBridges[server.id] = bridge
            server.state = .running
            log.info("  state → .running")
            persistRunningState()

            appLogger?.log(.info, cat: "http", msg: "Connected to \(server.manifest.name)")
        } catch {
            log.error("❌ connectHTTP() failed for '\(server.manifest.name)': \(error.localizedDescription)")
            appLogger?.log(.error, cat: "http", msg: "Failed to connect \(server.manifest.name)", meta: ["error": .string(error.localizedDescription)])
            server.state = .error("Failed to connect: \(error.localizedDescription)")
            throw ProcessManagerError.startFailed(error.localizedDescription)
        }
    }

    /// Disconnect from an HTTP MCP server.
    func disconnectHTTP(_ server: MCPServer) async {
        log.info("⏹️ disconnectHTTP() called for '\(server.manifest.name)'")
        appLogger?.log(.info, cat: "http", msg: "Disconnecting from \(server.manifest.name)")

        guard case .running = server.state else {
            log.warning("  skip — not running (state=\(String(describing: server.state)))")
            return
        }

        server.state = .stopping
        log.info("  state → .stopping")

        // Gracefully disconnect the HTTP bridge
        if let bridge = httpBridges[server.id] {
            await bridge.disconnect()
            httpBridges.removeValue(forKey: server.id)
            log.info("  HTTPBridge disconnected and removed")
        }

        server.state = .idle
        log.info("  state → .idle")
        persistRunningState()
        appLogger?.log(.info, cat: "http", msg: "Disconnected from \(server.manifest.name)")
        registry?.removeServerIfPendingConfigRemoval(server)
    }
}

// MARK: - Error Types

enum ProcessManagerError: LocalizedError, Sendable {
    case noRootDirectory
    case startFailed(String)
    case stopFailed(String)

    var errorDescription: String? {
        switch self {
        case .noRootDirectory:
            return L10n.string("error.process.noRootDirectory")
        case .startFailed(let reason):
            return L10n.format("error.process.startFailed", reason)
        case .stopFailed(let reason):
            return L10n.format("error.process.stopFailed", reason)
        }
    }
}
