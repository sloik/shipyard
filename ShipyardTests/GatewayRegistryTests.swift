import Testing
import Foundation
@testable import Shipyard

@Suite("GatewayRegistry", .timeLimit(.minutes(1)))
@MainActor
struct GatewayRegistryTests {

    // MARK: - Test Helpers

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

    private func makeRegistry() -> GatewayRegistry {
        let suiteName = "com.shipyard.test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        // Clean any stale state
        defaults.removePersistentDomain(forName: suiteName)
        return GatewayRegistry(defaults: defaults)
    }

    // MARK: - updateTools Tests

    @Test("updateTools adds tools with correct prefixed names")
    func updateToolsAddsToolsWithPrefixedNames() {
        let registry = makeRegistry()
        let tools = [
            makeRawTool(name: "run_command", description: "Run a shell command"),
            makeRawTool(name: "list_files", description: "List files in directory")
        ]

        registry.updateTools(mcpName: "mac-runner", rawTools: tools)

        #expect(registry.tools.count == 2)
        #expect(registry.tools[0].prefixedName == "mac-runner__run_command")
        #expect(registry.tools[1].prefixedName == "mac-runner__list_files")
        #expect(registry.tools[0].originalName == "run_command")
        #expect(registry.tools[1].originalName == "list_files")
        #expect(registry.tools[0].mcpName == "mac-runner")
        #expect(registry.tools[1].mcpName == "mac-runner")
        #expect(registry.tools[0].description == "Run a shell command")
        #expect(registry.tools[1].description == "List files in directory")
    }

    @Test("updateTools includes schema data correctly")
    func updateToolsIncludesSchemaData() {
        let registry = makeRegistry()
        let schema: [String: Any] = [
            "type": "object",
            "properties": [
                "command": ["type": "string"]
            ]
        ]
        let tools = [makeRawTool(name: "run", schema: schema)]

        registry.updateTools(mcpName: "test-mcp", rawTools: tools)

        #expect(registry.tools.count == 1)
        #expect(!registry.tools[0].inputSchema.isEmpty)
        // Verify schema can be decoded back
        if let decoded = try? JSONSerialization.jsonObject(with: registry.tools[0].inputSchema) as? [String: Any] {
            #expect(decoded["type"] as? String == "object")
        } else {
            Issue.record("Schema should be valid JSON")
        }
    }

    @Test("updateTools replaces old tools for same MCP")
    func updateToolsReplacesOldTools() {
        let registry = makeRegistry()

        // First update with 2 tools
        let tools1 = [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ]
        registry.updateTools(mcpName: "mcp1", rawTools: tools1)
        #expect(registry.tools.count == 2)

        // Second update with 3 different tools
        let tools2 = [
            makeRawTool(name: "tool_c"),
            makeRawTool(name: "tool_d"),
            makeRawTool(name: "tool_e")
        ]
        registry.updateTools(mcpName: "mcp1", rawTools: tools2)

        // Should have only the 3 new tools, not 5 total
        #expect(registry.tools.count == 3)
        #expect(registry.tools.allSatisfy { $0.mcpName == "mcp1" })
        #expect(registry.tools.map { $0.originalName }.sorted() == ["tool_c", "tool_d", "tool_e"])
    }

    @Test("updateTools with empty list clears tools for that MCP")
    func updateToolsWithEmptyListClearsTools() {
        let registry = makeRegistry()

        // Add some tools
        let tools = [makeRawTool(name: "tool1"), makeRawTool(name: "tool2")]
        registry.updateTools(mcpName: "mcp1", rawTools: tools)
        #expect(registry.tools.count == 2)

        // Update with empty list
        registry.updateTools(mcpName: "mcp1", rawTools: [])

        #expect(registry.tools.isEmpty)
    }

    @Test("updateTools preserves tools from other MCPs")
    func updateToolsPreservesOtherMCPs() {
        let registry = makeRegistry()

        // Add tools from mcp1
        registry.updateTools(mcpName: "mcp1", rawTools: [makeRawTool(name: "tool_a")])
        #expect(registry.tools.count == 1)

        // Add tools from mcp2
        registry.updateTools(mcpName: "mcp2", rawTools: [makeRawTool(name: "tool_b")])
        #expect(registry.tools.count == 2)

        // Update mcp1 with different tools
        registry.updateTools(mcpName: "mcp1", rawTools: [makeRawTool(name: "tool_c")])

        // Should have 2 tools: one from mcp1 (tool_c), one from mcp2 (tool_b)
        #expect(registry.tools.count == 2)
        let mcp1Tools = registry.tools.filter { $0.mcpName == "mcp1" }
        let mcp2Tools = registry.tools.filter { $0.mcpName == "mcp2" }
        #expect(mcp1Tools.count == 1)
        #expect(mcp1Tools[0].originalName == "tool_c")
        #expect(mcp2Tools.count == 1)
        #expect(mcp2Tools[0].originalName == "tool_b")
    }

    // MARK: - removeTools Tests

    @Test("removeTools removes all tools for given MCP")
    func removeToolsRemovesAllToolsForMCP() {
        let registry = makeRegistry()

        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ])
        registry.updateTools(mcpName: "mcp2", rawTools: [
            makeRawTool(name: "tool_c")
        ])
        #expect(registry.tools.count == 3)

        registry.removeTools(mcpName: "mcp1")

        #expect(registry.tools.count == 1)
        #expect(registry.tools[0].mcpName == "mcp2")
        #expect(registry.tools[0].originalName == "tool_c")
    }

    @Test("removeTools leaves other MCPs untouched")
    func removeToolsLeavesOtherMCPsUntouched() {
        let registry = makeRegistry()

        registry.updateTools(mcpName: "mcp1", rawTools: [makeRawTool(name: "tool_a")])
        registry.updateTools(mcpName: "mcp2", rawTools: [makeRawTool(name: "tool_b")])
        registry.updateTools(mcpName: "mcp3", rawTools: [makeRawTool(name: "tool_c")])

        registry.removeTools(mcpName: "mcp2")

        #expect(registry.tools.count == 2)
        let mcps = registry.tools.map { $0.mcpName }.sorted()
        #expect(mcps == ["mcp1", "mcp3"])
    }

    // MARK: - setMCPEnabled Tests

    @Test("setMCPEnabled(false) disables all tools for that MCP")
    func setMCPEnabledFalseDisablesAllTools() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ])

        // Verify initially enabled (default)
        #expect(registry.tools[0].enabled == true)
        #expect(registry.tools[1].enabled == true)

        registry.setMCPEnabled("mcp1", enabled: false)

        #expect(registry.tools[0].enabled == false)
        #expect(registry.tools[1].enabled == false)
        #expect(registry.isMCPEnabled("mcp1") == false)
    }

    @Test("setMCPEnabled(true) re-enables all tools for that MCP")
    func setMCPEnabledTrueReEnablesAllTools() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ])

        registry.setMCPEnabled("mcp1", enabled: false)
        #expect(registry.tools[0].enabled == false)

        registry.setMCPEnabled("mcp1", enabled: true)

        #expect(registry.tools[0].enabled == true)
        #expect(registry.tools[1].enabled == true)
        #expect(registry.isMCPEnabled("mcp1") == true)
    }

    // MARK: - setToolEnabled Tests

    @Test("setToolEnabled disables single tool while MCP stays enabled")
    func setToolEnabledDisablesSingleTool() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ])

        registry.setToolEnabled("mcp1__tool_a", enabled: false)

        #expect(registry.tools[0].enabled == false)
        #expect(registry.tools[1].enabled == true)
        #expect(registry.isMCPEnabled("mcp1") == true)
    }

    @Test("setToolEnabled override survives MCP disable/enable toggle")
    func setToolEnabledOverrideSurvivesMCPToggle() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ])

        // Disable tool_a explicitly
        registry.setToolEnabled("mcp1__tool_a", enabled: false)
        #expect(registry.tools[0].enabled == false)
        #expect(registry.tools[1].enabled == true)

        // Disable MCP
        registry.setMCPEnabled("mcp1", enabled: false)

        // tool_a should still be disabled (not re-enabled by MCP toggle)
        #expect(registry.tools[0].enabled == false)
        #expect(registry.tools[1].enabled == false)

        // Re-enable MCP
        registry.setMCPEnabled("mcp1", enabled: true)

        // tool_a should stay disabled (override), tool_b should be enabled
        #expect(registry.tools[0].enabled == false)
        #expect(registry.tools[1].enabled == true)
    }

    @Test("setToolEnabled can re-enable an overridden tool")
    func setToolEnabledCanReEnableOverriddenTool() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [makeRawTool(name: "tool_a")])

        registry.setToolEnabled("mcp1__tool_a", enabled: false)
        #expect(registry.tools[0].enabled == false)

        registry.setToolEnabled("mcp1__tool_a", enabled: true)

        #expect(registry.tools[0].enabled == true)
    }

    // MARK: - isToolEnabled Tests

    @Test("isToolEnabled returns true for enabled tool")
    func isToolEnabledReturnsTrueForEnabledTool() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [makeRawTool(name: "tool_a")])

        #expect(registry.isToolEnabled("mcp1__tool_a") == true)
    }

    @Test("isToolEnabled returns false for disabled tool")
    func isToolEnabledReturnsFalseForDisabledTool() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [makeRawTool(name: "tool_a")])

        registry.setToolEnabled("mcp1__tool_a", enabled: false)

        #expect(registry.isToolEnabled("mcp1__tool_a") == false)
    }

    @Test("isToolEnabled returns false for unknown tool")
    func isToolEnabledReturnsFalseForUnknownTool() {
        let registry = makeRegistry()

        #expect(registry.isToolEnabled("unknown__tool") == false)
    }

    // MARK: - isMCPEnabled Tests

    @Test("isMCPEnabled returns true by default")
    func isMCPEnabledReturnsTrueByDefault() {
        let registry = makeRegistry()

        #expect(registry.isMCPEnabled("new-mcp") == true)
    }

    @Test("isMCPEnabled returns false after disabling")
    func isMCPEnabledReturnsFalseAfterDisabling() {
        let registry = makeRegistry()

        registry.setMCPEnabled("mcp1", enabled: false)

        #expect(registry.isMCPEnabled("mcp1") == false)
    }

    // MARK: - toolCatalog Tests

    @Test("toolCatalog returns correct serialized dictionaries")
    func toolCatalogReturnsSerialized() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a", description: "Tool A", schema: ["type": "object"])
        ])

        let catalog = registry.toolCatalog()

        #expect(catalog.count == 1)
        let dict = catalog[0]
        #expect(dict["name"] as? String == "mcp1__tool_a")
        #expect(dict["mcp"] as? String == "mcp1")
        #expect(dict["original_name"] as? String == "tool_a")
        #expect(dict["description"] as? String == "Tool A")
        #expect(dict["enabled"] as? Bool == true)
        #expect(dict["inputSchema"] != nil)
    }

    @Test("toolCatalog includes all tools regardless of enabled state")
    func toolCatalogIncludesAllTools() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ])
        registry.setToolEnabled("mcp1__tool_a", enabled: false)

        let catalog = registry.toolCatalog()

        #expect(catalog.count == 2)
        let names = catalog.map { $0["name"] as? String }
        #expect(names.contains("mcp1__tool_a"))
        #expect(names.contains("mcp1__tool_b"))
    }

    // MARK: - enabledToolNames Tests

    @Test("enabledToolNames only returns enabled tools")
    func enabledToolNamesReturnsOnlyEnabled() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b"),
            makeRawTool(name: "tool_c")
        ])

        registry.setToolEnabled("mcp1__tool_a", enabled: false)
        registry.setToolEnabled("mcp1__tool_c", enabled: false)

        let enabled = registry.enabledToolNames()

        #expect(enabled.count == 1)
        #expect(enabled[0] == "mcp1__tool_b")
    }

    @Test("enabledToolNames returns empty when all disabled")
    func enabledToolNamesReturnsEmptyWhenAllDisabled() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [
            makeRawTool(name: "tool_a"),
            makeRawTool(name: "tool_b")
        ])

        registry.setMCPEnabled("mcp1", enabled: false)

        let enabled = registry.enabledToolNames()

        #expect(enabled.isEmpty)
    }

    @Test("enabledToolNames includes tools from multiple MCPs")
    func enabledToolNamesIncludesMultipleMCPs() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp1", rawTools: [makeRawTool(name: "tool_a")])
        registry.updateTools(mcpName: "mcp2", rawTools: [makeRawTool(name: "tool_b")])

        let enabled = registry.enabledToolNames()

        #expect(enabled.count == 2)
        #expect(enabled.contains("mcp1__tool_a"))
        #expect(enabled.contains("mcp2__tool_b"))
    }

    @Test("shipyard MCP is always enabled")
    func shipyardMCPAlwaysEnabled() {
        let registry = makeRegistry()
        registry.setMCPEnabled(GatewayRegistry.shipyardMCPName, enabled: false)
        #expect(registry.isMCPEnabled(GatewayRegistry.shipyardMCPName) == true)
    }

    @Test("shipyard tool defaults to enabled and persists with shipyard key format")
    func shipyardToolPersistenceKeyFormat() {
        let suiteName = "com.shipyard.test.shipyardkeys.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)

        let registry = GatewayRegistry(defaults: defaults)
        registry.updateTools(
            mcpName: GatewayRegistry.shipyardMCPName,
            rawTools: [makeRawTool(name: "shipyard_status"), makeRawTool(name: "shipyard_health")]
        )

        #expect(registry.isToolEnabled("shipyard__shipyard_status") == true)
        registry.setToolEnabled("shipyard__shipyard_status", enabled: false)
        #expect(defaults.object(forKey: "shipyard.tool.shipyard.shipyard_status.enabled") as? Bool == false)

        let restored = GatewayRegistry(defaults: defaults)
        restored.updateTools(
            mcpName: GatewayRegistry.shipyardMCPName,
            rawTools: [makeRawTool(name: "shipyard_status"), makeRawTool(name: "shipyard_health")]
        )
        #expect(restored.isToolEnabled("shipyard__shipyard_status") == false)
        #expect(restored.isToolEnabled("shipyard__shipyard_health") == true)
    }

    @Test("discoverShipyardTools uses shipyard_tools and stores shipyard__ namespaced tools")
    @available(macOS 14.0, *)
    func discoverShipyardToolsFromSocket() async {
        let registry = MCPRegistry()
        registry.ensureSyntheticShipyardServerRegistered()
        let processManager = ProcessManager()
        let socketServer = SocketServer()
        let gatewayRegistry = makeRegistry()

        await socketServer.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)
        gatewayRegistry.setSocketServer(socketServer)

        let count = await gatewayRegistry.discoverShipyardTools()
        #expect(count == 7)

        let shipyardTools = gatewayRegistry.tools.filter { $0.mcpName == GatewayRegistry.shipyardMCPName }
        #expect(shipyardTools.count == 7)
        #expect(shipyardTools.allSatisfy { $0.prefixedName.hasPrefix("shipyard__") })

        await socketServer.stop()
    }

    @Test("updateTools suppresses tools_changed when tool catalog is unchanged")
    func updateToolsSuppressesDuplicateNotificationWhenUnchanged() {
        let registry = makeRegistry()
        var notifications = 0
        registry.onToolsChangedForTesting = { notifications += 1 }

        let tools = [
            makeRawTool(name: "shipyard_status", description: "status"),
            makeRawTool(name: "shipyard_health", description: "health")
        ]

        registry.updateTools(mcpName: GatewayRegistry.shipyardMCPName, rawTools: tools)
        #expect(notifications == 1)

        registry.updateTools(mcpName: GatewayRegistry.shipyardMCPName, rawTools: tools)
        #expect(notifications == 1)
    }

    @Test("removeTools suppresses tools_changed when MCP has no tools")
    func removeToolsSuppressesNotificationWhenNothingRemoved() {
        let registry = makeRegistry()
        var notifications = 0
        registry.onToolsChangedForTesting = { notifications += 1 }

        registry.removeTools(mcpName: "missing-mcp")
        #expect(notifications == 0)
    }
}
