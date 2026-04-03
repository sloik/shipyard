import Testing
import Foundation
@testable import Shipyard

@Suite("MCPRegistry.rescan()")
@MainActor
struct MCPRegistryRescanTests {

    private func makeManifest(name: String = "test-server", version: String = "1.0.0") -> MCPManifest {
        let json = """
        {
            "name": "\(name)",
            "version": "\(version)",
            "description": "Test",
            "transport": "stdio",
            "command": "python3",
            "args": ["server.py"]
        }
        """.data(using: .utf8)!
        return try! JSONDecoder().decode(MCPManifest.self, from: json)
    }

    @Test("MCPRegistry has rescan method")
    func hasRescanMethod() async throws {
        let registry = MCPRegistry()
        // Verify rescan method exists and is callable
        await registry.rescan()
        // Should not throw
    }

    @Test("Server tracks orphaned state")
    func serverTracksOrphanedState() throws {
        let server = MCPServer(manifest: makeManifest())

        // Initial state should not be orphaned
        #expect(!server.isOrphaned)

        // Can be marked orphaned
        server.isOrphaned = true
        #expect(server.isOrphaned)
    }

    @Test("Server tracks config needs restart flag")
    func serverTracksConfigNeedsRestart() throws {
        let server = MCPServer(manifest: makeManifest())

        // Initial state should not need restart
        #expect(!server.configNeedsRestart)

        // Can be flagged
        server.configNeedsRestart = true
        #expect(server.configNeedsRestart)
    }

    @Test("MCPRegistry correctly identifies running state")
    func identifiesRunningState() throws {
        let server = MCPServer(manifest: makeManifest())

        // Idle state
        #expect(!server.state.isRunning)

        // Running state
        server.state = ServerState.running
        #expect(server.state.isRunning)

        // Other states
        server.state = ServerState.idle
        #expect(!server.state.isRunning)

        server.state = ServerState.starting
        #expect(!server.state.isRunning)

        server.state = ServerState.stopping
        #expect(!server.state.isRunning)
    }

    @Test("Manifest comparison logic works")
    func manifestComparisonLogic() throws {
        let manifest1 = makeManifest(name: "test", version: "1.0.0")
        let manifest2 = makeManifest(name: "test", version: "1.0.0")
        let manifest3 = makeManifest(name: "test", version: "2.0.0")

        // Same content should be equal
        #expect(manifest1.version == manifest2.version)
        #expect(manifest1.command == manifest2.command)

        // Different content should differ
        #expect(manifest1.version != manifest3.version)
    }

    @Test("Registry maintains server deduplication")
    func maintainsDeduplication() async throws {
        let registry = MCPRegistry()

        let manifest = makeManifest()
        let server1 = MCPServer(manifest: manifest)
        let server2 = MCPServer(manifest: manifest)

        // Register first server
        try registry.register(server1)
        #expect(registry.registeredServers.count == 1)

        // Attempt to register server with same name should throw
        do {
            try registry.register(server2)
            #expect(Bool(false), "Should have thrown for duplicate name")
        } catch RegistryError.serverAlreadyRegistered {
            #expect(Bool(true))  // Expected
        }
    }

    @Test("Registry finds server by name")
    func findsServerByName() async throws {
        let registry = MCPRegistry()

        let server = MCPServer(manifest: makeManifest(name: "my-server"))
        try registry.register(server)

        // Server should be findable by name
        #expect(registry.server(named: "my-server") != nil)
        #expect(registry.server(named: "nonexistent") == nil)
    }
}
