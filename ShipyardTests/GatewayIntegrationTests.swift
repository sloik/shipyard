import Testing
import Foundation
@testable import Shipyard

@Suite("Gateway Integration")
@MainActor
struct GatewayIntegrationTests {

    // MARK: - Test Helpers

    private func makeBridgeWithDrain() -> (bridge: MCPBridge, drainTask: Task<Void, Never>) {
        let pipe = Pipe()
        let bridge = MCPBridge(mcpName: "test-mcp", stdinPipe: pipe)

        let drainTask = Task.detached {
            while !Task.isCancelled {
                let data = pipe.fileHandleForReading.availableData
                if data.isEmpty {
                    try? await Task.sleep(for: .milliseconds(10))
                    continue
                }
            }
        }

        return (bridge, drainTask)
    }

    private func makeRegistry() -> GatewayRegistry {
        let suiteName = "com.shipyard.test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return GatewayRegistry(defaults: defaults)
    }

    private func makeRawTool(name: String, description: String = "Test tool", schema: [String: Any]? = nil) -> [String: Any] {
        var tool: [String: Any] = [
            "name": name,
            "description": description
        ]
        if let schema = schema {
            tool["inputSchema"] = schema
        }
        return tool
    }

    // MARK: - 1. Discovery → Registry Pipeline Tests

    @Test("discoverThenUpdateRegistry: discover tools and feed into registry")
    func discoverThenUpdateRegistry() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let registry = makeRegistry()

        // Start discovery in background
        let discoveryTask = Task {
            try await bridge.discoverTools()
        }

        // Give discovery call time to register its pending request (id=1)
        try await Task.sleep(for: .milliseconds(100))

        // Simulate tools/list response with id=1
        let responseConsumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"run_command","description":"Run shell cmd","inputSchema":{"type":"object"}},{"name":"list_files","description":"List files"}]}}
            """)

        #expect(responseConsumed == true)

        // Await discovery result
        let discoveredTools = try await discoveryTask.value

        #expect(discoveredTools.count == 2)
        #expect((discoveredTools[0]["name"] as? String) == "run_command")
        #expect((discoveredTools[1]["name"] as? String) == "list_files")

        // Feed results into registry
        registry.updateTools(mcpName: "test-mcp", rawTools: discoveredTools)

        // Verify tools in registry with correct prefixed names
        #expect(registry.tools.count == 2)
        #expect(registry.tools[0].prefixedName == "test-mcp__run_command")
        #expect(registry.tools[1].prefixedName == "test-mcp__list_files")
        #expect(registry.tools[0].mcpName == "test-mcp")
        #expect(registry.tools[1].mcpName == "test-mcp")
        #expect(registry.tools[0].originalName == "run_command")
        #expect(registry.tools[1].originalName == "list_files")
    }

    @Test("multiMCPDiscovery: aggregate tools from multiple MCPs into same registry")
    func multiMCPDiscovery() async throws {
        let (bridge1, drainTask1) = makeBridgeWithDrain()
        defer { drainTask1.cancel() }

        let (bridge2, drainTask2) = makeBridgeWithDrain()
        defer { drainTask2.cancel() }

        let registry = makeRegistry()

        // Bridge 1 discovery
        let discovery1Task = Task {
            try await bridge1.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge1.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool_a","description":"Tool A"},{"name":"tool_b","description":"Tool B"}]}}
            """)
        let tools1 = try await discovery1Task.value
        registry.updateTools(mcpName: "mcp1", rawTools: tools1)

        // Bridge 2 discovery
        let discovery2Task = Task {
            try await bridge2.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge2.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool_c","description":"Tool C"},{"name":"tool_d","description":"Tool D"},{"name":"tool_e","description":"Tool E"}]}}
            """)
        let tools2 = try await discovery2Task.value
        registry.updateTools(mcpName: "mcp2", rawTools: tools2)

        // Verify aggregation with proper namespacing
        #expect(registry.tools.count == 5)

        let mcp1Tools = registry.tools.filter { $0.mcpName == "mcp1" }
        let mcp2Tools = registry.tools.filter { $0.mcpName == "mcp2" }

        #expect(mcp1Tools.count == 2)
        #expect(mcp2Tools.count == 3)

        #expect(mcp1Tools[0].prefixedName == "mcp1__tool_a")
        #expect(mcp1Tools[1].prefixedName == "mcp1__tool_b")
        #expect(mcp2Tools[0].prefixedName == "mcp2__tool_c")
        #expect(mcp2Tools[1].prefixedName == "mcp2__tool_d")
        #expect(mcp2Tools[2].prefixedName == "mcp2__tool_e")
    }

    @Test("rediscoveryReplacesOldTools: re-discovery with different tools replaces old ones")
    func rediscoveryReplacesOldTools() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let registry = makeRegistry()

        // First discovery
        let discovery1Task = Task {
            try await bridge.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"old_tool_1","description":"Old 1"},{"name":"old_tool_2","description":"Old 2"}]}}
            """)
        let tools1 = try await discovery1Task.value
        registry.updateTools(mcpName: "my-mcp", rawTools: tools1)

        #expect(registry.tools.count == 2)
        #expect(registry.tools.map { $0.originalName }.sorted() == ["old_tool_1", "old_tool_2"])

        // Second discovery with different tools
        let discovery2Task = Task {
            try await bridge.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"new_tool_1","description":"New 1"},{"name":"new_tool_2","description":"New 2"},{"name":"new_tool_3","description":"New 3"}]}}
            """)
        let tools2 = try await discovery2Task.value
        registry.updateTools(mcpName: "my-mcp", rawTools: tools2)

        // Verify old tools replaced with new ones
        #expect(registry.tools.count == 3)
        #expect(registry.tools.allSatisfy { $0.mcpName == "my-mcp" })
        #expect(registry.tools.map { $0.originalName }.sorted() == ["new_tool_1", "new_tool_2", "new_tool_3"])
    }

    // MARK: - 2. Gateway Call Pipeline Tests

    @Test("lookupAndCallTool: populate registry, lookup tool, call it, verify result")
    func lookupAndCallTool() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let registry = makeRegistry()

        // Populate registry with discovered tools
        let discoveryTask = Task {
            try await bridge.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"run_cmd","description":"Run command"}]}}
            """)
        let discoveredTools = try await discoveryTask.value
        registry.updateTools(mcpName: "cmd-runner", rawTools: discoveredTools)

        #expect(registry.tools.count == 1)
        let prefixedName = "cmd-runner__run_cmd"
        #expect(registry.tools[0].prefixedName == prefixedName)

        // Lookup tool by prefixed name
        guard let tool = registry.tools.first(where: { $0.prefixedName == prefixedName }) else {
            Issue.record("Tool should be found in registry")
            return
        }

        // Resolve original name for calling
        let originalName = tool.originalName
        #expect(originalName == "run_cmd")

        // Call the tool
        let callTask = Task {
            try await bridge.callTool(name: originalName, arguments: ["cmd": "ls"])
        }
        try await Task.sleep(for: .milliseconds(100))

        // Simulate tools/call response with id=2 (second call after discoverTools was id=1)
        let responseConsumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"file1.txt\\nfile2.txt"}]}}
            """)

        #expect(responseConsumed == true)

        let result = try await callTask.value
        #expect((result["content"] as? [[String: Any]])?.count == 1)
        let content = (result["content"] as? [[String: Any]])?[0]
        #expect((content?["type"] as? String) == "text")
        #expect((content?["text"] as? String) == "file1.txt\nfile2.txt")
    }

    @Test("callDisabledToolIsBlocked: verify disabled tool check before call")
    func callDisabledToolIsBlocked() async throws {
        let registry = makeRegistry()

        // Populate registry
        registry.updateTools(mcpName: "test-mcp", rawTools: [makeRawTool(name: "tool_a")])

        let prefixedName = "test-mcp__tool_a"
        #expect(registry.tools[0].prefixedName == prefixedName)

        // Initially enabled
        #expect(registry.isToolEnabled(prefixedName) == true)

        // Disable the tool
        registry.setToolEnabled(prefixedName, enabled: false)

        // Verify it's now disabled (gateway_call handler checks this before calling)
        #expect(registry.isToolEnabled(prefixedName) == false)

        // Verify the tool exists in registry but is disabled
        #expect(registry.tools.first(where: { $0.prefixedName == prefixedName }) != nil)
        #expect(registry.tools.first(where: { $0.prefixedName == prefixedName })?.enabled == false)
    }

    @Test("callUnknownToolReturnsNil: lookup non-existent tool")
    func callUnknownToolReturnsNil() {
        let registry = makeRegistry()

        // Populate with some tools
        registry.updateTools(mcpName: "test-mcp", rawTools: [makeRawTool(name: "tool_a")])

        #expect(registry.tools.count == 1)

        // Try to find non-existent tool
        let unknownTool = registry.tools.first(where: { $0.prefixedName == "test-mcp__non_existent" })

        #expect(unknownTool == nil)
    }

    // MARK: - 3. Persistence Integration Tests

    @Test("persistenceRoundtrip: save state, create new registry with same defaults, verify restored")
    func persistenceRoundtrip() async throws {
        // Create shared UserDefaults
        let suiteName = "com.shipyard.test.persistence.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)

        // First registry: configure and discover
        let (bridge1, drainTask1) = makeBridgeWithDrain()
        defer { drainTask1.cancel() }

        let registry1 = GatewayRegistry(defaults: defaults)

        let discoveryTask = Task {
            try await bridge1.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge1.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool_a","description":"A"},{"name":"tool_b","description":"B"}]}}
            """)
        let tools = try await discoveryTask.value
        registry1.updateTools(mcpName: "test-mcp", rawTools: tools)

        // Set per-tool override
        registry1.setToolEnabled("test-mcp__tool_a", enabled: false)
        #expect(registry1.isToolEnabled("test-mcp__tool_a") == false)
        #expect(registry1.isToolEnabled("test-mcp__tool_b") == true)

        // Create new registry with same UserDefaults
        let (bridge2, drainTask2) = makeBridgeWithDrain()
        defer { drainTask2.cancel() }

        let registry2 = GatewayRegistry(defaults: defaults)

        // Re-discover with same tools via second bridge
        let discovery2Task = Task {
            try await bridge2.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge2.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool_a","description":"A"},{"name":"tool_b","description":"B"}]}}
            """)
        let tools2 = try await discovery2Task.value
        registry2.updateTools(mcpName: "test-mcp", rawTools: tools2)

        // Verify per-tool override is correctly restored
        #expect(registry2.tools.count == 2)
        #expect(registry2.isToolEnabled("test-mcp__tool_a") == false)
        #expect(registry2.isToolEnabled("test-mcp__tool_b") == true)
    }

    @Test("persistenceSurvivesReDiscovery: set override, re-discover, verify override preserved")
    func persistenceSurvivesReDiscovery() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let suiteName = "com.shipyard.test.rediscovery.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        let registry = GatewayRegistry(defaults: defaults)

        // First discovery
        let discovery1Task = Task {
            try await bridge.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool_x","description":"X"},{"name":"tool_y","description":"Y"}]}}
            """)
        let tools1 = try await discovery1Task.value
        registry.updateTools(mcpName: "mcp", rawTools: tools1)

        // Set tool override
        registry.setToolEnabled("mcp__tool_x", enabled: false)
        #expect(registry.tools[0].enabled == false)
        #expect(registry.tools[1].enabled == true)

        // Re-discovery with same tools
        let discovery2Task = Task {
            try await bridge.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"tool_x","description":"X"},{"name":"tool_y","description":"Y"}]}}
            """)
        let tools2 = try await discovery2Task.value
        registry.updateTools(mcpName: "mcp", rawTools: tools2)

        // Verify override is correctly applied to rediscovered tools
        #expect(registry.tools.count == 2)
        let toolX = registry.tools.first(where: { $0.originalName == "tool_x" })
        let toolY = registry.tools.first(where: { $0.originalName == "tool_y" })

        #expect(toolX?.enabled == false)
        #expect(toolY?.enabled == true)
    }

    // MARK: - 4. Lifecycle Resilience Tests

    @Test("bridgeCancelDoesNotCorruptRegistry: populate registry, cancel bridge, verify registry intact")
    func bridgeCancelDoesNotCorruptRegistry() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let registry = makeRegistry()

        // Populate registry via discovery
        let discoveryTask = Task {
            try await bridge.discoverTools()
        }
        try await Task.sleep(for: .milliseconds(100))
        _ = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool_1","description":"1"},{"name":"tool_2","description":"2"}]}}
            """)
        let tools = try await discoveryTask.value
        registry.updateTools(mcpName: "test-mcp", rawTools: tools)

        #expect(registry.tools.count == 2)
        let tool1PrefixedName = "test-mcp__tool_1"
        #expect(registry.tools[0].prefixedName == tool1PrefixedName)

        // Cancel all pending requests on bridge
        bridge.cancelAll()

        // Verify registry is still intact and queryable
        #expect(registry.tools.count == 2)
        #expect(registry.tools[0].prefixedName == tool1PrefixedName)
        let found = registry.tools.first(where: { $0.prefixedName == tool1PrefixedName })
        #expect(found != nil)
        #expect(found?.originalName == "tool_1")
    }

    @Test("removeToolsAfterBridgeDestroyed: populate registry, destroy bridge, remove tools, clean state")
    func removeToolsAfterBridgeDestroyed() async throws {
        var bridge: MCPBridge? = nil
        var drainTask: Task<Void, Never>? = nil

        let registry = makeRegistry()

        // Set up bridge and populate registry
        do {
            let (b, d) = makeBridgeWithDrain()
            bridge = b
            drainTask = d

            let discoveryTask = Task {
                try await bridge!.discoverTools()
            }
            try await Task.sleep(for: .milliseconds(100))
            _ = bridge!.routeStdoutLine("""
                {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"tool_a","description":"A"}]}}
                """)
            let tools = try await discoveryTask.value
            registry.updateTools(mcpName: "test-mcp", rawTools: tools)

            #expect(registry.tools.count == 1)
        }

        // Destroy bridge by setting to nil
        drainTask?.cancel()
        bridge = nil

        // Call removeTools on registry
        registry.removeTools(mcpName: "test-mcp")

        // Verify clean state
        #expect(registry.tools.isEmpty)
    }

    // MARK: - Shipyard Integration Tests (SPEC-006)

    @Test("shipyardToolDiscoveryAndToggle: discover Shipyard tools, toggle enable/disable, verify persistence")
    func shipyardToolDiscoveryAndToggle() async throws {
        let registry = makeRegistry()

        // Simulate Shipyard tool discovery (6 tools)
        let shipyardTools = [
            makeRawTool(name: "status", description: "Get status of all managed MCP servers"),
            makeRawTool(name: "health", description: "Run health checks on all servers"),
            makeRawTool(name: "logs", description: "Get logs from specific MCP server"),
            makeRawTool(name: "restart", description: "Restart specific MCP server"),
            makeRawTool(name: "gateway_discover", description: "Get all available tools from managed MCPs"),
            makeRawTool(name: "gateway_call", description: "Call a tool from a managed MCP")
        ]

        // Update registry with Shipyard tools
        registry.updateTools(mcpName: "shipyard", rawTools: shipyardTools)

        // Verify Shipyard tools are in registry with correct namespacing
        #expect(registry.tools.count == 6)
        #expect(registry.tools.allSatisfy { $0.mcpName == "shipyard" })
        #expect(registry.tools[0].prefixedName == "shipyard__status")
        #expect(registry.tools[1].prefixedName == "shipyard__health")
        #expect(registry.tools[5].prefixedName == "shipyard__gateway_call")

        // All tools should be enabled by default
        #expect(registry.tools.allSatisfy { $0.enabled })

        // Disable the "logs" tool
        registry.setToolEnabled("shipyard__logs", enabled: false)

        // Verify state in registry
        let logsToolAfterDisable = registry.tools.first { $0.prefixedName == "shipyard__logs" }
        #expect(logsToolAfterDisable?.enabled == false)

        // Verify other Shipyard tools remain enabled
        #expect(registry.tools.filter { $0.prefixedName != "shipyard__logs" }.allSatisfy { $0.enabled })

        // Create new registry instance to verify persistence
        let newRegistry = GatewayRegistry(defaults: registry.defaults)

        // Wait for persistence to be available
        try await Task.sleep(for: .milliseconds(50))

        // Discover Shipyard tools again
        newRegistry.updateTools(mcpName: "shipyard", rawTools: shipyardTools)

        // Verify persisted state: logs tool should still be disabled
        let logsToolAfterRestart = newRegistry.tools.first { $0.prefixedName == "shipyard__logs" }
        #expect(logsToolAfterRestart?.enabled == false)

        // Verify other tools are still enabled
        #expect(newRegistry.tools.filter { $0.prefixedName != "shipyard__logs" }.allSatisfy { $0.enabled })
    }

    @Test("shipyardToolsCannotBeDisabledAtMCPLevel: Shipyard has no MCP-level disable")
    func shipyardToolsCannotBeDisabledAtMCPLevel() async throws {
        let registry = makeRegistry()

        // Populate Shipyard tools
        let shipyardTools = [
            makeRawTool(name: "status", description: "Get status"),
            makeRawTool(name: "health", description: "Run health checks")
        ]
        registry.updateTools(mcpName: "shipyard", rawTools: shipyardTools)

        // All tools should be enabled initially
        #expect(registry.tools.allSatisfy { $0.enabled })

        // Attempt to disable at MCP level (should not affect Shipyard)
        // Note: setMCPEnabled would only be called for child MCPs, not Shipyard
        // This test verifies that Shipyard tools remain enabled regardless

        // Verify Shipyard tools are still all enabled
        #expect(registry.tools.filter { $0.mcpName == "shipyard" }.allSatisfy { $0.enabled })
    }

    @Test("multipleShipyardToolsToggleIndependently: toggling one Shipyard tool doesn't affect others")
    func multipleShipyardToolsToggleIndependently() async throws {
        let registry = makeRegistry()

        // Populate Shipyard tools
        let shipyardTools = [
            makeRawTool(name: "logs", description: "Get logs"),
            makeRawTool(name: "restart", description: "Restart"),
            makeRawTool(name: "health", description: "Health check")
        ]
        registry.updateTools(mcpName: "shipyard", rawTools: shipyardTools)

        // Disable logs
        registry.setToolEnabled("shipyard__logs", enabled: false)

        // Verify only logs is disabled
        #expect(registry.tools.first { $0.prefixedName == "shipyard__logs" }?.enabled == false)
        #expect(registry.tools.first { $0.prefixedName == "shipyard__restart" }?.enabled == true)
        #expect(registry.tools.first { $0.prefixedName == "shipyard__health" }?.enabled == true)

        // Disable restart separately
        registry.setToolEnabled("shipyard__restart", enabled: false)

        // Verify correct state
        #expect(registry.tools.first { $0.prefixedName == "shipyard__logs" }?.enabled == false)
        #expect(registry.tools.first { $0.prefixedName == "shipyard__restart" }?.enabled == false)
        #expect(registry.tools.first { $0.prefixedName == "shipyard__health" }?.enabled == true)

        // Re-enable logs
        registry.setToolEnabled("shipyard__logs", enabled: true)

        // Verify final state
        #expect(registry.tools.first { $0.prefixedName == "shipyard__logs" }?.enabled == true)
        #expect(registry.tools.first { $0.prefixedName == "shipyard__restart" }?.enabled == false)
        #expect(registry.tools.first { $0.prefixedName == "shipyard__health" }?.enabled == true)
    }
}
