import Foundation
import Darwin
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "SocketServer")

/// ISO8601 date formatter for JSON responses
nonisolated(unsafe) private let iso8601Formatter: ISO8601DateFormatter = {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter
}()

/// Thread-safe weak reference box for passing @MainActor references across isolation boundaries.
/// Used to avoid capturing @MainActor-isolated self in DispatchSource handlers.
private struct WeakServerBox: @unchecked Sendable {
    weak var server: SocketServer?
}

// MARK: - Free functions for DispatchSource creation (must be outside @MainActor class)

/// Creates the accept DispatchSource. Free function to guarantee no @MainActor isolation
/// inheritance — static methods on @MainActor classes are still actor-isolated.
private func _makeAcceptSource(serverFD: Int32, box: WeakServerBox) -> DispatchSourceRead {
    let flags = fcntl(serverFD, F_GETFL)
    _ = fcntl(serverFD, F_SETFL, flags | O_NONBLOCK)

    let source = DispatchSource.makeReadSource(fileDescriptor: serverFD, queue: .global())

    source.setEventHandler {
        while true {
            var clientAddr = sockaddr_un()
            var clientAddrLen = socklen_t(MemoryLayout<sockaddr_un>.size)

            let clientFD = withUnsafeMutablePointer(to: &clientAddr) { addrPtr in
                addrPtr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPtr in
                    accept(serverFD, sockaddrPtr, &clientAddrLen)
                }
            }

            if clientFD < 0 {
                let err = errno
                if err != EAGAIN && err != EWOULDBLOCK {
                    log.error("Accept failed: errno=\(err)")
                }
                break
            }

            log.debug("Accepted client connection: fd=\(clientFD)")
            _ = fcntl(clientFD, F_SETFL, fcntl(clientFD, F_GETFL) | O_NONBLOCK)

            Task { @MainActor in
                box.server?.setupClientReadSource(fd: clientFD)
            }
        }
    }

    source.setCancelHandler {
        log.info("Accept source cancelled")
    }

    return source
}

/// Creates a client read DispatchSource. Free function to guarantee no @MainActor isolation.
private func _makeClientReadSource(clientFD: Int32, box: WeakServerBox) -> DispatchSourceRead {
    let source = DispatchSource.makeReadSource(fileDescriptor: clientFD, queue: .global())

    source.setEventHandler {
        var buffer = [UInt8](repeating: 0, count: 4096)
        let bytesRead = Darwin.read(clientFD, &buffer, 4096)

        if bytesRead <= 0 {
            Task { @MainActor in
                box.server?.cleanupClient(fd: clientFD)
            }
            return
        }

        if let str = String(bytes: Array(buffer.prefix(bytesRead)), encoding: .utf8) {
            Task { @MainActor in
                box.server?.processClientData(fd: clientFD, data: str)
            }
        }
    }

    source.setCancelHandler {
        Darwin.close(clientFD)
        log.debug("Client connection closed: fd=\(clientFD)")
    }

    return source
}

// MARK: - Socket Server

/// Unix domain socket server for external MCP query and control
/// Listens on the centralized runtime socket path.
@MainActor final class SocketServer {
    private let socketPath: String
    private var serverSocket: Int32 = -1
    private var acceptSource: DispatchSourceRead?
    private var clientSources: [Int32: DispatchSourceRead] = [:]
    private var clientBuffers: [Int32: String] = [:]

    /// References to main services (set at startup)
    private weak var registry: MCPRegistry?
    private weak var processManager: ProcessManager?
    private weak var gatewayRegistry: GatewayRegistry?
    private var appLogger: AppLogger?
    private var pendingToolsChangedNotification: DispatchWorkItem?
    private let toolsChangedDebounceInterval: TimeInterval = 0.15

    init(paths: PathManager = .shared) {
        self.socketPath = paths.socketFile.path
        log.info("SocketServer initialized with socket path: \(self.socketPath)")
    }

    // MARK: - Lifecycle

    /// Starts the socket server, accepting client connections in background
    func start(registry: MCPRegistry, processManager: ProcessManager, gatewayRegistry: GatewayRegistry, appLogger: AppLogger? = nil) async {
        self.registry = registry
        self.processManager = processManager
        self.gatewayRegistry = gatewayRegistry
        self.appLogger = appLogger

        log.info("Starting SocketServer")

        // Ensure directory exists
        let socketDir = (socketPath as NSString).deletingLastPathComponent
        do {
            try FileManager.default.createDirectory(
                atPath: socketDir,
                withIntermediateDirectories: true,
                attributes: nil
            )
            log.info("Socket directory ensured: \(socketDir)")
        } catch {
            log.error("Failed to create socket directory: \(error.localizedDescription)")
            return
        }

        // Remove stale socket
        try? FileManager.default.removeItem(atPath: socketPath)

        // Create and bind socket
        serverSocket = socket(AF_UNIX, SOCK_STREAM, 0)
        guard serverSocket >= 0 else {
            log.error("Failed to create socket")
            return
        }
        log.info("Socket created: fd=\(self.serverSocket)")

        // Bind to path
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = socketPath.utf8CString
        guard pathBytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
            log.error("Socket path too long: \(self.socketPath)")
            close(serverSocket)
            serverSocket = -1
            return
        }

        pathBytes.withUnsafeBufferPointer { srcBuffer in
            withUnsafeMutableBytes(of: &addr.sun_path) { dstBuffer in
                dstBuffer.copyMemory(from: UnsafeRawBufferPointer(srcBuffer))
            }
        }

        var addrCopy = addr
        let addrLen = MemoryLayout<sockaddr_un>.size

        let bindResult = withUnsafePointer(to: &addrCopy) { ptr in
            bind(serverSocket, UnsafeRawPointer(ptr).assumingMemoryBound(to: sockaddr.self), socklen_t(addrLen))
        }

        guard bindResult == 0 else {
            log.error("Failed to bind socket: \(errno)")
            close(serverSocket)
            serverSocket = -1
            return
        }
        log.info("Socket bound to: \(self.socketPath)")

        // Listen
        guard listen(serverSocket, SOMAXCONN) == 0 else {
            log.error("Failed to listen on socket: \(errno)")
            close(serverSocket)
            serverSocket = -1
            return
        }
        log.info("Socket listening (backlog=\(SOMAXCONN))")

        // Start accept loop in detached task (blocking I/O runs off main actor)
        startAcceptLoop()

        log.info("SocketServer started successfully")
        appLogger?.log(.info, cat: "socket-server", msg: "Socket server started", meta: ["path": .string(socketPath)])
    }

    /// Stops the socket server and cleans up
    func stop() async {
        log.info("Stopping SocketServer")
        appLogger?.log(.info, cat: "socket-server", msg: "Socket server stopped")
        pendingToolsChangedNotification?.cancel()
        pendingToolsChangedNotification = nil

        acceptSource?.cancel()
        acceptSource = nil

        for (_, source) in clientSources {
            source.cancel()
        }
        clientSources.removeAll()
        clientBuffers.removeAll()

        if serverSocket >= 0 {
            close(serverSocket)
            serverSocket = -1
        }

        try? FileManager.default.removeItem(atPath: socketPath)
        log.info("SocketServer stopped, socket file removed")
    }

    /// Restarts only the socket listener (does not restart child MCP processes).
    func restartSocketListener() async throws {
        guard let registry,
              let processManager,
              let gatewayRegistry else {
            throw SocketServerError.servicesUnavailable
        }

        appLogger?.log(.info, cat: "socket-server", msg: "Restarting socket listener")
        await stop()
        await start(
            registry: registry,
            processManager: processManager,
            gatewayRegistry: gatewayRegistry,
            appLogger: appLogger
        )

        guard serverSocket >= 0 else {
            throw SocketServerError.startFailed("Socket listener failed to restart")
        }
    }

    // MARK: - Socket Accept Loop

    /// Starts the accept loop using DispatchSource for non-blocking I/O.
    private func startAcceptLoop() {
        let box = WeakServerBox(server: self)
        log.info("Accept loop starting with DispatchSource (non-blocking)")
        let source = _makeAcceptSource(serverFD: serverSocket, box: box)
        source.resume()
        acceptSource = source
    }

    /// Sets up DispatchSource for reading from a client socket
    fileprivate func setupClientReadSource(fd clientFD: Int32) {
        clientBuffers[clientFD] = ""
        let box = WeakServerBox(server: self)
        let source = _makeClientReadSource(clientFD: clientFD, box: box)
        source.resume()
        clientSources[clientFD] = source
    }

    /// Processes data received from a client, extracts complete lines, and dispatches requests
    fileprivate func processClientData(fd clientFD: Int32, data: String) {
        // Append to buffer
        clientBuffers[clientFD, default: ""].append(data)
        
        guard var buffer = clientBuffers[clientFD] else { return }

        // Extract and process complete lines
        while let newlineIdx = buffer.firstIndex(of: "\n") {
            let line = String(buffer[..<newlineIdx]).trimmingCharacters(in: .whitespacesAndNewlines)
            buffer.removeFirst(buffer.distance(from: buffer.startIndex, to: buffer.index(after: newlineIdx)))

            if !line.isEmpty {
                // Launch a Task to handle the request without blocking current execution
                Task { [weak self] in
                    let response = await self?.dispatchRequest(line) ?? "{\"error\": \"Server unavailable\"}"
                    
                    // Write response back to client
                    let responseStr = response + "\n"
                    if let responseData = responseStr.data(using: .utf8) {
                        let written = responseData.withUnsafeBytes { respBuffer in
                            Darwin.write(clientFD, respBuffer.baseAddress!, respBuffer.count)
                        }
                        if written < 0 {
                            let err = errno
                            log.warning("Encountered write failure \(err) \(String(cString: strerror(err)))")
                            // Cleanup on write failure
                            Task { @MainActor [weak self] in
                                self?.cleanupClient(fd: clientFD)
                            }
                        }
                    }
                }
            }
        }

        // Update buffer
        clientBuffers[clientFD] = buffer
    }

    /// Cleans up a client connection
    fileprivate func cleanupClient(fd clientFD: Int32) {
        clientSources[clientFD]?.cancel()
        clientSources.removeValue(forKey: clientFD)
        clientBuffers.removeValue(forKey: clientFD)
    }



    // MARK: - Request Dispatch

    /// Dispatches a JSON request line and returns a JSON response line
    func dispatchRequest(_ requestLine: String) async -> String {
        guard let data = requestLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let method = json["method"] as? String else {
            appLogger?.log(.debug, cat: "socket-server", msg: "Request: (invalid format)")
            return errorResponse("Invalid request format")
        }

        appLogger?.log(.debug, cat: "socket-server", msg: "Request: \(method)")
        let params = json["params"] as? [String: Any] ?? [:]

        switch method {
        case "status":
            return await handleStatus()
        case "logs":
            return await handleLogs(params: params)
        case "restart":
            return await handleRestart(params: params)
        case "health":
            return await handleHealth()
        case "gateway_discover":
            return await handleGatewayDiscover()
        case "gateway_catalog":
            return handleGatewayCatalog()
        case "shipyard_tools":
            return handleShipyardTools()
        case "gateway_call":
            return await handleGatewayCall(params: params)
        case "gateway_set_enabled":
            return await handleGatewaySetEnabled(params: params)
        case "log_event":
            return handleLogEvent(params: params)
        default:
            return errorResponse("Unknown method: \(method)")
        }
    }

    // MARK: - Method Handlers

    /// Handles "log_event" — receives live log entries forwarded from ShipyardBridge
    private func handleLogEvent(params: [String: Any]) -> String {
        guard let ts = params["ts"] as? String,
              let level = params["level"] as? String,
              let cat = params["cat"] as? String,
              let src = params["src"] as? String,
              let msg = params["msg"] as? String else {
            return errorResponse("Invalid log_event: missing required fields")
        }

        // Parse optional meta
        var metaDict: [String: AnyCodableValue]? = nil
        if let metaRaw = params["meta"] as? [String: Any] {
            var meta: [String: AnyCodableValue] = [:]
            for (key, value) in metaRaw {
                if let s = value as? String { meta[key] = .string(s) }
                else if let i = value as? Int { meta[key] = .int(i) }
                else if let d = value as? Double { meta[key] = .double(d) }
                else if let b = value as? Bool { meta[key] = .bool(b) }
            }
            metaDict = meta.isEmpty ? nil : meta
        }

        let entry = BridgeLogEntry(ts: ts, level: level, cat: cat, src: src, msg: msg, meta: metaDict)
        appLogger?.logStore?.append(entry)

        return successResponse(["ok": true])
    }

    /// Handles "status" request — returns array of all servers
    private func handleStatus() async -> String {
        guard let registry = registry else {
            return errorResponse("Registry not available")
        }

        let serverData: [[String: Any]] = registry.registeredServers.map { server in
            var stateStr = "idle"
            switch server.state {
            case .idle:
                stateStr = "idle"
            case .starting:
                stateStr = "starting"
            case .running:
                stateStr = "running"
            case .stopping:
                stateStr = "stopping"
            case .error(let msg):
                stateStr = "error: \(msg)"
            }

            let healthStr: String
            if server.isBuiltin {
                healthStr = "healthy"
            } else {
                switch server.healthStatus {
                case .healthy:
                    healthStr = "healthy"
                case .unhealthy(let msg):
                    healthStr = "unhealthy: \(msg)"
                case .unknown:
                    healthStr = "unknown"
                }
            }

            var dict: [String: Any] = [
                "name": server.manifest.name,
                "version": server.manifest.version,
                "state": stateStr,
                "health": healthStr,
                "auto_restart": server.autoRestartEnabled,
                "restart_count": server.restartCount,
                "dependencies_ok": server.isBuiltin ? true : server.dependencyResults.allSatisfy { $0.satisfied }
            ]

            if let pid = server.processStats?.pid {
                dict["pid"] = pid
            }

            if let cpu = server.processStats?.cpuPercent {
                dict["cpu_percent"] = cpu
            }

            if let mem = server.processStats?.memoryMB {
                dict["memory_mb"] = mem
            }

            if let lastCheck = server.lastHealthCheck {
                dict["last_health_check"] = iso8601Formatter.string(from: lastCheck)
            }

            return dict
        }

        return successResponse(serverData)
    }

    /// Handles "logs" request
    private func handleLogs(params: [String: Any]) async -> String {
        guard let name = params["name"] as? String else {
            return errorResponse("Missing required parameter: name")
        }

        guard let registry = registry else {
            return errorResponse("Registry not available")
        }

        guard let server = registry.server(named: name) else {
            return errorResponse("server not found: \(name)")
        }

        let lines = params["lines"] as? Int ?? 50
        let level = params["level"] as? String

        var entries = server.stderrBuffer

        // Filter by level if specified
        if let levelStr = level, let minLevel = LogLevel(rawValue: levelStr) {
            let minValue = levelValue(minLevel)
            entries = entries.filter { levelValue($0.level) >= minValue }
        }

        // Keep only the last N
        if entries.count > lines {
            entries = Array(entries.suffix(lines))
        }

        let logData: [[String: Any]] = entries.map { entry in
            [
                "timestamp": iso8601Formatter.string(from: entry.timestamp),
                "message": entry.message,
                "level": entry.level.rawValue,
                "source": entry.source.rawValue
            ]
        }

        return successResponse(logData)
    }

    /// Handles "restart" request
    private func handleRestart(params: [String: Any]) async -> String {
        guard let name = params["name"] as? String else {
            return errorResponse("Missing required parameter: name")
        }

        guard let registry = registry,
              let processManager = processManager else {
            return errorResponse("Services not available")
        }

        guard let server = registry.server(named: name) else {
            return errorResponse("server not found: \(name)")
        }

        do {
            if server.isBuiltin {
                try await restartSocketListener()
                return successResponse(["ok": true])
            }
            try await processManager.restart(server)
            return successResponse(["ok": true])
        } catch {
            return errorResponse("Restart failed: \(error.localizedDescription)")
        }
    }

    /// Handles "health" request — runs health checks on all servers
    private func handleHealth() async -> String {
        guard let registry = registry,
              let processManager = processManager else {
            return errorResponse("Services not available")
        }

        let healthData: [[String: Any?]] = registry.registeredServers.map { server in
            let isRunning = server.isBuiltin || (server.state == .running && processManager.isProcessRunning(server.id))

            var dict: [String: Any?] = [
                "name": server.manifest.name,
                "healthy": isRunning
            ]

            if !isRunning {
                dict["message"] = "Process not running"
            }

            return dict
        }

        return successResponse(healthData)
    }

    /// Handles "gateway_discover" — triggers tool discovery across all running MCPs and returns aggregated catalog
    private func handleGatewayDiscover() async -> String {
        guard let registry = registry,
              let processManager = processManager,
              let gatewayRegistry = gatewayRegistry else {
            return errorResponse("Services not available")
        }

        // Discover tools from each running MCP
        for server in registry.registeredServers where server.state == .running {
            do {
                _ = try await gatewayRegistry.discoverTools(for: server, processManager: processManager)
            } catch {
                log.warning("Gateway discovery failed for \(server.manifest.name): \(error.localizedDescription)")
                // Don't fail the whole discovery — skip this MCP
            }
        }
        _ = await gatewayRegistry.discoverShipyardTools()

        let toolCount = gatewayRegistry.toolCatalog().count
        appLogger?.log(.info, cat: "socket-server", msg: "Gateway discovery complete", meta: ["tool_count": .int(toolCount)])
        return successResponse(["tools": gatewayRegistry.toolCatalog()])
    }

    /// Handles "gateway_catalog" — returns current aggregated catalog without triggering discovery.
    /// This is side-effect-free and safe for refresh loops.
    private func handleGatewayCatalog() -> String {
        guard let gatewayRegistry = gatewayRegistry else {
            return errorResponse("Services not available")
        }
        return successResponse(["tools": gatewayRegistry.toolCatalog()])
    }

    /// Handles "shipyard_tools" — returns Shipyard's own MCP tool catalog.
    private func handleShipyardTools() -> String {
        let tools: [[String: Any]] = [
            ["name": "shipyard_status", "description": "Returns Shipyard server status", "inputSchema": [:]],
            ["name": "shipyard_health", "description": "Runs health checks for managed MCP servers", "inputSchema": [:]],
            ["name": "shipyard_logs", "description": "Returns logs for a specific MCP server", "inputSchema": [:]],
            ["name": "shipyard_restart", "description": "Restarts a managed MCP server", "inputSchema": [:]],
            ["name": "shipyard_gateway_discover", "description": "Discovers and aggregates gateway tools", "inputSchema": [:]],
            ["name": "shipyard_gateway_call", "description": "Calls a gateway tool by namespaced name", "inputSchema": [:]],
            ["name": "shipyard_gateway_set_enabled", "description": "Enables or disables MCPs or tools in gateway", "inputSchema": [:]]
        ]
        return successResponse(["tools": tools])
    }
    
    /// Handles "gateway_call" — forwards a tool call to a child MCP via MCPBridge
    private func handleGatewayCall(params: [String: Any]) async -> String {
        guard let toolName = params["tool"] as? String else {
            return errorResponse("Missing required parameter: tool")
        }

        guard let arguments = params["arguments"] as? [String: Any] else {
            return errorResponse("Missing required parameter: arguments")
        }

        guard let gatewayRegistry = gatewayRegistry else {
            return errorResponse("Gateway not available")
        }

        appLogger?.log(.info, cat: "socket-server", msg: "Gateway call: \(toolName)")

        // Look up the tool in the gateway registry to get mcpName and originalName
        guard let tool = gatewayRegistry.tools.first(where: { $0.prefixedName == toolName }) else {
            return errorResponse("Unknown tool: \(toolName)")
        }

        // Check if tool is enabled
        guard gatewayRegistry.isToolEnabled(toolName) else {
            return errorResponse("tool_unavailable: \(toolName)")
        }

        if tool.mcpName == GatewayRegistry.shipyardMCPName {
            return await callShipyardTool(name: tool.originalName, arguments: arguments)
        }

        guard let registry = registry,
              let processManager = processManager else {
            return errorResponse("Services not available")
        }

        // Find the MCPServer by name
        guard let server = registry.server(named: tool.mcpName) else {
            return errorResponse("MCP '\(tool.mcpName)' not found")
        }

        // Check if server is running
        guard server.state == .running else {
            return errorResponse("MCP '\(tool.mcpName)' is not running")
        }

        // Get the bridge for this server
        guard let bridge = processManager.bridge(for: server) else {
            return errorResponse("No bridge for '\(tool.mcpName)'")
        }

        // Call the tool via the bridge
        do {
            let result = try await bridge.callTool(name: tool.originalName, arguments: arguments)
            return successResponse(result)
        } catch let error as MCPBridgeError {
            return errorResponse(error.localizedDescription)
        } catch {
            return errorResponse("Tool call failed: \(error.localizedDescription)")
        }
    }
    
    /// Handles "gateway_set_enabled" — enables/disables an MCP or specific tool
    private func handleGatewaySetEnabled(params: [String: Any]) async -> String {
        guard let enabled = params["enabled"] as? Bool else {
            return errorResponse("Missing required parameter: enabled (must be boolean)")
        }
        
        guard let gatewayRegistry = gatewayRegistry else {
            return errorResponse("Gateway not available")
        }
        
        // Check if setting MCP-level or tool-level
        if let mcpName = params["mcp"] as? String {
            if mcpName == GatewayRegistry.shipyardMCPName {
                return errorResponse("Shipyard MCP cannot be disabled")
            }
            gatewayRegistry.setMCPEnabled(mcpName, enabled: enabled)
            return successResponse(["ok": true])
        } else if let toolName = params["tool"] as? String {
            gatewayRegistry.setToolEnabled(toolName, enabled: enabled)
            return successResponse(["ok": true])
        } else {
            return errorResponse("Missing required parameter: mcp or tool")
        }
    }

    private func callShipyardTool(name: String, arguments: [String: Any]) async -> String {
        switch name {
        case "shipyard_status":
            return await handleStatus()
        case "shipyard_health":
            return await handleHealth()
        case "shipyard_logs":
            return await handleLogs(params: arguments)
        case "shipyard_restart":
            return await handleRestart(params: arguments)
        case "shipyard_gateway_discover":
            return await handleGatewayDiscover()
        case "shipyard_gateway_call":
            return await handleGatewayCall(params: arguments)
        case "shipyard_gateway_set_enabled":
            return await handleGatewaySetEnabled(params: arguments)
        default:
            return errorResponse("Unknown Shipyard tool: \(name)")
        }
    }

    // MARK: - Notifications

    /// Sends a tools_changed notification to all connected ShipyardBridge clients
    /// Called when GatewayRegistry tools change due to MCP lifecycle events or discovery
    @MainActor
    func notifyToolsChanged() {
        pendingToolsChangedNotification?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            self?.broadcastToolsChangedNow()
        }
        pendingToolsChangedNotification = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + toolsChangedDebounceInterval, execute: workItem)
    }

    @MainActor
    private func broadcastToolsChangedNow() {
        pendingToolsChangedNotification = nil
        let notification: [String: Any] = [
            "method": "tools_changed",
            "params": [:]
        ]

        guard let jsonData = try? JSONSerialization.data(
            withJSONObject: notification,
            options: []
        ) else {
            log.error("Failed to serialize tools_changed notification")
            return
        }

        guard let notificationStr = String(data: jsonData, encoding: .utf8) else {
            log.error("Failed to encode tools_changed notification")
            return
        }

        let notificationLine = notificationStr + "\n"
        guard let notificationData = notificationLine.data(using: .utf8) else {
            log.error("Failed to convert tools_changed to data")
            return
        }

        log.info("Broadcasting tools_changed notification to \(self.clientSources.count) clients")

        // Send to all connected clients
        for (clientFD, _) in clientSources {
            let written = notificationData.withUnsafeBytes { buffer in
                Darwin.write(clientFD, buffer.baseAddress!, buffer.count)
            }

            if written < 0 {
                let err = errno
                log.warning("Failed to send tools_changed to client fd=\(clientFD): errno=\(err)")
            } else {
                log.debug("tools_changed sent to client fd=\(clientFD)")
            }
        }
    }

    // MARK: - Response Formatting

    /// Creates a success response JSON
    func successResponse(_ result: Any) -> String {
        guard let jsonData = try? JSONSerialization.data(
            withJSONObject: ["result": result],
            options: []
        ) else {
            return "{\"error\": \"Failed to serialize response\"}"
        }

        return String(data: jsonData, encoding: .utf8) ?? "{\"error\": \"Encoding error\"}"
    }

    /// Creates an error response JSON
    func errorResponse(_ message: String) -> String {
        guard let jsonData = try? JSONSerialization.data(
            withJSONObject: ["error": message],
            options: []
        ) else {
            return "{\"error\": \"Internal error\"}"
        }

        return String(data: jsonData, encoding: .utf8) ?? "{\"error\": \"Encoding error\"}"
    }

    // MARK: - Helpers

    /// Returns numeric value for log level (for filtering)
    func levelValue(_ level: LogLevel) -> Int {
        switch level {
        case .debug:
            return 0
        case .info:
            return 1
        case .warning:
            return 2
        case .error:
            return 3
        }
    }
}

enum SocketServerError: LocalizedError {
    case servicesUnavailable
    case startFailed(String)

    var errorDescription: String? {
        switch self {
        case .servicesUnavailable:
            return L10n.string("error.socketServer.servicesUnavailable")
        case .startFailed(let reason):
            return L10n.format("error.socketServer.startFailed", reason)
        }
    }
}
