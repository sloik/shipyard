import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "GatewayRegistry")

/// A tool exposed through the gateway, aggregated from a child MCP
struct GatewayTool: Sendable, Identifiable {
    let prefixedName: String      // "mac-runner__run_command"
    let mcpName: String           // "mac-runner"
    let originalName: String      // "run_command"
    let description: String
    let inputSchema: Data         // Raw JSON data (passthrough from child)
    var enabled: Bool
    
    var id: String { prefixedName }
}

/// Aggregates tool catalogs from all managed child MCPs
@Observable @MainActor final class GatewayRegistry {
    static let shipyardMCPName = "shipyard"

    private(set) var tools: [GatewayTool] = []
    private(set) var mcpEnabled: [String: Bool] = [:]  // MCP-level enable/disable
    private(set) var toolOverrides: [String: Bool] = [:] // per-tool overrides (prefixedName → enabled)

    /// App logger — injected from ShipyardApp
    var appLogger: AppLogger?

    /// Socket server for sending tool change notifications (weak ref to avoid cycles)
    private weak var socketServer: SocketServer?
    var onToolsChangedForTesting: (() -> Void)?

    private let defaults: UserDefaults
    private let mcpEnabledPrefix = "gateway.mcp.enabled."
    private let toolEnabledPrefix = "gateway.tool.enabled."
    private let shipyardToolEnabledPrefix = "shipyard.tool.shipyard."

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        loadPersistedState()
    }

    /// Set the socket server for sending notifications
    func setSocketServer(_ server: SocketServer) {
        self.socketServer = server
    }

    /// Discover Shipyard's own tools from the local socket server.
    /// Returns number of discovered tools.
    func discoverShipyardTools() async -> Int {
        guard let socketServer else { return 0 }

        let request: [String: Any] = ["method": "shipyard_tools"]
        guard let requestData = try? JSONSerialization.data(withJSONObject: request),
              let requestLine = String(data: requestData, encoding: .utf8) else {
            return 0
        }

        let responseLine = await socketServer.dispatchRequest(requestLine)
        guard let responseData = responseLine.data(using: .utf8),
              let responseJSON = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any],
              let result = responseJSON["result"] as? [String: Any],
              let rawTools = result["tools"] as? [[String: Any]] else {
            return 0
        }

        updateTools(mcpName: Self.shipyardMCPName, rawTools: rawTools)
        return rawTools.count
    }

    /// Discover tools for a running server via its transport bridge and update catalog.
    /// Returns number of discovered tools.
    func discoverTools(for server: MCPServer, processManager: ProcessManager) async throws -> Int {
        if server.source == .synthetic {
            return 0
        }

        guard server.state == .running else { return 0 }
        guard let bridge = processManager.bridgeProtocol(for: server) else {
            throw MCPBridgeError.notRunning(server.manifest.name)
        }

        let profiler = StartupProfiler.shared
        let phaseLabel = "gateway.discoverTools.\(server.manifest.name)"
        profiler.begin(phaseLabel)
        defer { profiler.end(phaseLabel) }
        let startedAt = CFAbsoluteTimeGetCurrent()
        let tools = try await bridge.discoverTools()
        let durationMs = max(0, (CFAbsoluteTimeGetCurrent() - startedAt) * 1000)
        profiler.recordToolDiscovery(name: server.manifest.name, toolCount: tools.count, durationMs: durationMs)

        updateTools(mcpName: server.manifest.name, rawTools: tools)
        return tools.count
    }
    
    /// Update the tool catalog from discovered tools
    /// Called after MCPBridge.discoverTools() for each running child MCP
    func updateTools(mcpName: String, rawTools: [[String: Any]]) {
        let previousSignature = toolSignature(for: mcpName)

        // Remove old tools for this MCP
        tools.removeAll { $0.mcpName == mcpName }

        // Add new tools
        for rawTool in rawTools {
            guard let name = rawTool["name"] as? String else { continue }
            let description = rawTool["description"] as? String ?? ""
            let schema = rawTool["inputSchema"] ?? rawTool["input_schema"]
            let schemaData: Data
            if let schema = schema {
                schemaData = (try? JSONSerialization.data(withJSONObject: schema)) ?? Data()
            } else {
                schemaData = Data()
            }

            let prefixed = "\(mcpName)__\(name)"
            let mcpOn = isShipyardServerName(mcpName) ? true : (mcpEnabled[mcpName] ?? true)  // default enabled
            let toolOverride = toolOverrides[prefixed]
            let enabled = toolOverride ?? mcpOn

            tools.append(GatewayTool(
                prefixedName: prefixed,
                mcpName: mcpName,
                originalName: name,
                description: description,
                inputSchema: schemaData,
                enabled: enabled
            ))
        }

        log.info("Updated tools for \(mcpName): \(rawTools.count) tools")
        appLogger?.log(.info, cat: "gateway-reg", msg: "Updated tools for \(mcpName)", meta: ["count": .int(rawTools.count)])

        let currentSignature = toolSignature(for: mcpName)
        if currentSignature != previousSignature {
            socketServer?.notifyToolsChanged()
            onToolsChangedForTesting?()
        } else {
            log.debug("Suppressing tools_changed for \(mcpName): no effective catalog change")
        }
    }

    /// Remove all tools for an MCP (called when it stops)
    func removeTools(mcpName: String) {
        let removedCount = tools.filter { $0.mcpName == mcpName }.count
        tools.removeAll { $0.mcpName == mcpName }
        log.info("Removed tools for \(mcpName)")
        appLogger?.log(.info, cat: "gateway-reg", msg: "Removed tools for \(mcpName)")

        if removedCount > 0 {
            socketServer?.notifyToolsChanged()
            onToolsChangedForTesting?()
        } else {
            log.debug("Suppressing tools_changed for \(mcpName): no tools to remove")
        }
    }
    
    /// Set MCP-level enabled state
    func setMCPEnabled(_ mcpName: String, enabled: Bool) {
        if isShipyardServerName(mcpName) {
            return
        }

        mcpEnabled[mcpName] = enabled
        defaults.set(enabled, forKey: mcpEnabledPrefix + mcpName)

        // Update individual tool enabled states (unless overridden)
        for i in tools.indices where tools[i].mcpName == mcpName {
            if toolOverrides[tools[i].prefixedName] == nil {
                tools[i].enabled = enabled
            }
        }
        log.info("MCP \(mcpName) enabled=\(enabled)")
        appLogger?.log(.info, cat: "gateway-reg", msg: "MCP \(mcpName) enabled=\(enabled)")
    }
    
    /// Set per-tool override
    func setToolEnabled(_ prefixedName: String, enabled: Bool) {
        toolOverrides[prefixedName] = enabled
        defaults.set(enabled, forKey: toolDefaultsKey(for: prefixedName))

        if let idx = tools.firstIndex(where: { $0.prefixedName == prefixedName }) {
            tools[idx].enabled = enabled
        }
        log.info("Tool \(prefixedName) enabled=\(enabled)")
        appLogger?.log(.info, cat: "gateway-reg", msg: "Tool \(prefixedName) enabled=\(enabled)")
    }
    
    /// Check if a specific tool is enabled (MCP-level + tool-level)
    func isToolEnabled(_ prefixedName: String) -> Bool {
        guard let tool = tools.first(where: { $0.prefixedName == prefixedName }) else { return false }
        return tool.enabled
    }
    
    /// Check if an MCP is enabled
    func isMCPEnabled(_ mcpName: String) -> Bool {
        if isShipyardServerName(mcpName) {
            return true
        }
        return mcpEnabled[mcpName] ?? true  // default enabled
    }
    
    /// Get all enabled tools as serializable dictionaries (for gateway_discover response)
    func toolCatalog() -> [[String: Any]] {
        return tools.map { tool in
            var dict: [String: Any] = [
                "name": tool.prefixedName,
                "mcp": tool.mcpName,
                "original_name": tool.originalName,
                "description": tool.description,
                "enabled": tool.enabled
            ]
            if let schema = try? JSONSerialization.jsonObject(with: tool.inputSchema) {
                dict["inputSchema"] = schema
            }
            return dict
        }
    }
    
    /// Get enabled tool names only
    func enabledToolNames() -> [String] {
        tools.filter { $0.enabled }.map { $0.prefixedName }
    }

    /// Returns tools for a server sorted by un-namespaced tool name (case-insensitive).
    /// Uses prefixed name as a deterministic tie-breaker.
    func sortedTools(for mcpName: String) -> [GatewayTool] {
        tools
            .filter { $0.mcpName == mcpName }
            .sorted {
                let lhs = $0.originalName.localizedCaseInsensitiveCompare($1.originalName)
                if lhs != .orderedSame {
                    return lhs == .orderedAscending
                }
                return $0.prefixedName.localizedCaseInsensitiveCompare($1.prefixedName) == .orderedAscending
            }
    }

    func isShipyardServer(_ tool: GatewayTool) -> Bool {
        isShipyardServerName(tool.mcpName)
    }

    private func isShipyardServerName(_ mcpName: String) -> Bool {
        mcpName == Self.shipyardMCPName
    }

    private func toolSignature(for mcpName: String) -> [String] {
        tools
            .filter { $0.mcpName == mcpName }
            .map { tool in
                "\(tool.prefixedName)|\(tool.description)|\(tool.enabled)|\(tool.inputSchema.base64EncodedString())"
            }
            .sorted()
    }
    
    // MARK: - Persistence
    
    private func loadPersistedState() {
        // Load MCP-level states
        let allKeys = defaults.dictionaryRepresentation().keys
        for key in allKeys {
            if key.hasPrefix(mcpEnabledPrefix) {
                let mcpName = String(key.dropFirst(mcpEnabledPrefix.count))
                mcpEnabled[mcpName] = defaults.bool(forKey: key)
            }
            if key.hasPrefix(toolEnabledPrefix) {
                let toolName = String(key.dropFirst(toolEnabledPrefix.count))
                toolOverrides[toolName] = defaults.bool(forKey: key)
            }
            if key.hasPrefix(shipyardToolEnabledPrefix) {
                var toolName = String(key.dropFirst(shipyardToolEnabledPrefix.count))
                if toolName.hasSuffix(".enabled") {
                    toolName.removeLast(".enabled".count)
                }
                toolOverrides["\(Self.shipyardMCPName)__\(toolName)"] = defaults.bool(forKey: key)
            }
        }
    }

    private func toolDefaultsKey(for prefixedName: String) -> String {
        let components = prefixedName.split(separator: "__", maxSplits: 1, omittingEmptySubsequences: false)
        guard components.count == 2 else {
            return toolEnabledPrefix + prefixedName
        }

        let mcpName = String(components[0])
        let toolName = String(components[1])
        if isShipyardServerName(mcpName) {
            return shipyardToolEnabledPrefix + toolName + ".enabled"
        }
        return toolEnabledPrefix + prefixedName
    }
}
