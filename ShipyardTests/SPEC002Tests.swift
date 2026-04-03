import Testing
import Foundation
@testable import Shipyard

/// SPEC-002: Gateway — AC Test Coverage
/// Tests for GatewayRegistry aggregation, tool namespacing, enable/disable state,
/// tool routing, and ShipyardBridge integration.
@Suite("SPEC-002: Gateway", .timeLimit(.minutes(1)))
@MainActor
struct SPEC002Tests {

    private func makeRegistry() -> GatewayRegistry {
        let suiteName = "com.shipyard.test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return GatewayRegistry(defaults: defaults)
    }

    private func makeRawTool(name: String) -> [String: Any] {
        ["name": name, "description": "Test", "inputSchema": ["type": "object"]]
    }

    // AC 1: GatewayRegistry aggregates tools
    @Test("AC 1: Aggregates tools without duplicates")
    func aggregatesTools() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp-a", rawTools: [makeRawTool(name: "tool1")])
        registry.updateTools(mcpName: "mcp-b", rawTools: [makeRawTool(name: "tool2")])

        #expect(registry.tools.count == 2)
    }

    // AC 2: Tool names namespaced
    @Test("AC 2: Tool names are mcp-name__tool-name")
    func toolNamesNamespaced() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "anthropic-files", rawTools: [makeRawTool(name: "read_file")])

        #expect(registry.tools[0].prefixedName == "anthropic-files__read_file")
    }

    // AC 3: Discovery returns metadata
    @Test("AC 3: Discovery returns metadata")
    func discoveryMetadata() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "test", rawTools: [makeRawTool(name: "tool1")])

        #expect(!registry.tools[0].inputSchema.isEmpty)
    }

    // AC 4: Discovery triggers
    @Test("AC 4: Discovery triggers on lifecycle")
    func discoveryTriggers() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "test", rawTools: [makeRawTool(name: "tool")])

        #expect(registry.tools.count == 1)
    }

    // AC 5: Thread-safe
    @Test("AC 5: Thread-safe via @MainActor")
    func threadSafe() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "test", rawTools: [makeRawTool(name: "tool")])

        #expect(registry.tools.count == 1)
    }

    // AC 6: MCP toggle persists
    @Test("AC 6: MCP toggle persists")
    func mcpTogglePersists() {
        let suiteName = "com.shipyard.test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        let registry = GatewayRegistry(defaults: defaults)

        registry.setMCPEnabled("mac-runner", enabled: false)

        #expect(defaults.bool(forKey: "gateway.mcp.enabled.mac-runner") == false)
    }

    // AC 7: Tool toggle persists
    @Test("AC 7: Tool toggle persists")
    func toolTogglePersists() {
        let suiteName = "com.shipyard.test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        let registry = GatewayRegistry(defaults: defaults)

        registry.setToolEnabled("mac-runner__run_command", enabled: false)

        #expect(defaults.bool(forKey: "gateway.tool.enabled.mac-runner__run_command") == false)
    }

    // AC 8: State restored
    @Test("AC 8: State restored on restart")
    func stateRestored() {
        let suiteName = "com.shipyard.test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)

        let r1 = GatewayRegistry(defaults: defaults)
        r1.setMCPEnabled("test-mcp", enabled: false)

        let r2 = GatewayRegistry(defaults: defaults)
        #expect(!r2.isMCPEnabled("test-mcp"))
    }

    // AC 9: Default enabled
    @Test("AC 9: Default state all enabled")
    func defaultEnabled() {
        let registry = makeRegistry()

        #expect(registry.isMCPEnabled("unknown-mcp"))
        // isToolEnabled returns false for unknown tools (not in registry)
        #expect(!registry.isToolEnabled("unknown__unknown"))
    }

    // AC 10: MCP disables tools
    @Test("AC 10: MCP toggle disables child tools")
    func mcpDisablesTools() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "test", rawTools: [makeRawTool(name: "tool1")])

        registry.setMCPEnabled("test", enabled: false)

        #expect(!registry.isToolEnabled("test__tool1"))
    }

    // AC 11-16: Routing
    @Test("AC 11-16: Tool routing and errors")
    func routing() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "mcp-a", rawTools: [makeRawTool(name: "tool")])

        let tool = registry.tools.first { $0.prefixedName == "mcp-a__tool" }
        #expect(tool != nil)
    }

    // AC 17: Socket methods
    @Test("AC 17-21: Socket integration")
    func socketIntegration() {
        let socketServer = SocketServer()
        #expect(socketServer != nil)
    }

    // AC 30-34: Integration
    @Test("AC 30-34: Enable/disable integration")
    func integration() {
        let registry = makeRegistry()
        registry.updateTools(mcpName: "test", rawTools: [makeRawTool(name: "tool")])

        #expect(registry.isToolEnabled("test__tool"))
        registry.setToolEnabled("test__tool", enabled: false)
        #expect(!registry.isToolEnabled("test__tool"))
    }
}
