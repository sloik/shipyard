import Foundation
import Testing
@testable import Shipyard

@Suite("SPEC-020: Gateway Ordering and Tool Sort", .timeLimit(.minutes(1)))
@MainActor
struct SPEC020Tests {

    private func makeServer(name: String, source: MCPSource) -> MCPServer {
        let manifest = MCPManifest(
            name: name,
            version: "1.0",
            description: "Test server",
            transport: "stdio",
            command: "/usr/bin/test",
            args: [],
            env: nil,
            env_secret_keys: nil,
            dependencies: nil,
            health_check: nil,
            logging: nil,
            install: nil
        )
        return MCPServer(manifest: manifest, source: source)
    }

    private func makeRawTool(name: String, description: String = "Test tool") -> [String: Any] {
        [
            "name": name,
            "description": description
        ]
    }

    private func makeGatewayRegistry() -> GatewayRegistry {
        let suiteName = "com.shipyard.spec020.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return GatewayRegistry(defaults: defaults)
    }

    @Test("Gateway sidebar ordering uses canonical source groups")
    func gatewaySidebarCanonicalOrdering() throws {
        let registry = MCPRegistry()
        try registry.register(makeServer(name: "pencil", source: .config))
        try registry.register(makeServer(name: "alpha-json", source: .config))
        try registry.register(makeServer(name: "bravo-manifest", source: .manifest))
        try registry.register(makeServer(name: "alpha-manifest", source: .manifest))
        try registry.register(makeServer(name: "Shipyard", source: .synthetic))

        let names = registry.sortedServers.map { $0.manifest.name }
        #expect(names == ["Shipyard", "alpha-manifest", "bravo-manifest", "alpha-json", "pencil"])
    }

    @Test("Manifest servers sort before config servers even with same initial letter")
    func manifestBeforeConfigWithSameInitialLetter() throws {
        let registry = MCPRegistry()
        try registry.register(makeServer(name: "alpha-manifest", source: .manifest))
        try registry.register(makeServer(name: "alpha-config", source: .config))

        let sorted = registry.sortedServers
        #expect(sorted.count == 2)
        #expect(sorted[0].source == .manifest)
        #expect(sorted[1].source == .config)
    }

    @Test("Gateway tools are sorted A→Z by un-namespaced name")
    func toolsSortedAlphabeticallyByOriginalName() {
        let registry = makeGatewayRegistry()
        registry.updateTools(mcpName: "test-mcp", rawTools: [
            makeRawTool(name: "zebra_tool"),
            makeRawTool(name: "alpha_tool"),
            makeRawTool(name: "middle_tool")
        ])

        let names = registry.sortedTools(for: "test-mcp").map { $0.originalName }
        #expect(names == ["alpha_tool", "middle_tool", "zebra_tool"])
    }

    @Test("Tool enable toggle does not affect display order")
    func togglingToolEnabledDoesNotAffectSortOrder() {
        let registry = makeGatewayRegistry()
        registry.updateTools(mcpName: "test-mcp", rawTools: [
            makeRawTool(name: "zebra_tool"),
            makeRawTool(name: "alpha_tool"),
            makeRawTool(name: "middle_tool")
        ])
        registry.setToolEnabled("test-mcp__middle_tool", enabled: false)

        let names = registry.sortedTools(for: "test-mcp").map { $0.originalName }
        #expect(names == ["alpha_tool", "middle_tool", "zebra_tool"])
    }

    @Test("Re-discovery re-sorts updated tool list")
    func rediscoveryResortsTools() {
        let registry = makeGatewayRegistry()
        registry.updateTools(mcpName: "test-mcp", rawTools: [
            makeRawTool(name: "zeta"),
            makeRawTool(name: "beta")
        ])
        registry.updateTools(mcpName: "test-mcp", rawTools: [
            makeRawTool(name: "gamma"),
            makeRawTool(name: "alpha"),
            makeRawTool(name: "epsilon")
        ])

        let names = registry.sortedTools(for: "test-mcp").map { $0.originalName }
        #expect(names == ["alpha", "epsilon", "gamma"])
    }

    @Test("No tools for server returns empty list")
    func noToolsReturnsEmptyList() {
        let registry = makeGatewayRegistry()
        let tools = registry.sortedTools(for: "missing-mcp")
        #expect(tools.isEmpty)
    }
}
