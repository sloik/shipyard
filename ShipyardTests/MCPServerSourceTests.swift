import Testing
import Foundation
@testable import Shipyard

@Suite("MCPServer Source & Transport")
@MainActor
struct MCPServerSourceTests {

    // MARK: - Helper Methods

    private func makeManifest(name: String = "test-server") -> MCPManifest {
        let json = """
        {
            "name": "\(name)",
            "version": "1.0.0",
            "description": "Test server",
            "transport": "stdio",
            "command": "python3",
            "args": ["server.py"]
        }
        """.data(using: .utf8)!
        return try! JSONDecoder().decode(MCPManifest.self, from: json)
    }

    // MARK: - Default Initialization Tests

    @Test("Default init has source=.manifest, transport=.stdio")
    func defaultInitHasManifestSourceAndStdio() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        #expect(server.source == .manifest)
        #expect(server.transport == .stdio)
    }

    @Test("Default init sets isHTTP=false")
    func defaultInitIsHTTPFalse() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        #expect(server.isHTTP == false)
    }

    @Test("Default init sets disabled=false")
    func defaultInitDisabledFalse() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        #expect(server.disabled == false)
    }

    // MARK: - Config-Sourced Initialization Tests

    @Test("Config-sourced init sets source=.config")
    func configSourcedInitHasConfigSource() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .config)

        #expect(server.source == .config)
    }

    @Test("Config-sourced init can have transport=.stdio")
    func configSourcedCanBeStdio() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .config, transport: .stdio)

        #expect(server.source == .config)
        #expect(server.transport == .stdio)
        #expect(server.isHTTP == false)
    }

    @Test("Config-sourced init can have transport=.streamableHTTP")
    func configSourcedCanBeHTTP() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .config, transport: .streamableHTTP)

        #expect(server.source == .config)
        #expect(server.transport == .streamableHTTP)
        #expect(server.isHTTP == true)
    }

    // MARK: - Transport Property Tests

    @Test("HTTP transport sets isHTTP=true")
    func httpTransportSetsIsHTTPTrue() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, transport: .streamableHTTP)

        #expect(server.transport == .streamableHTTP)
        #expect(server.isHTTP == true)
    }

    @Test("Stdio transport sets isHTTP=false")
    func stdioTransportSetsIsHTTPFalse() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, transport: .stdio)

        #expect(server.transport == .stdio)
        #expect(server.isHTTP == false)
    }

    @Test("isHTTP computed property works correctly")
    func isHTTPComputedPropertyAccurate() {
        let manifest = makeManifest()

        let stdioServer = MCPServer(manifest: manifest, transport: .stdio)
        #expect(stdioServer.isHTTP == false)

        let httpServer = MCPServer(manifest: manifest, transport: .streamableHTTP)
        #expect(httpServer.isHTTP == true)
    }

    // MARK: - CWD Tests

    @Test("configCwd is stored correctly")
    func configCwdStoredCorrectly() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .config)

        server.configCwd = "/tmp/mock-my-mcp"

        #expect(server.configCwd == "/tmp/mock-my-mcp")
    }

    @Test("configCwd defaults to nil")
    func configCwdDefaultsToNil() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        #expect(server.configCwd == nil)
    }

    @Test("configCwd can be set and updated")
    func configCwdCanBeUpdated() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        server.configCwd = "/path/1"
        #expect(server.configCwd == "/path/1")

        server.configCwd = "/path/2"
        #expect(server.configCwd == "/path/2")

        server.configCwd = nil
        #expect(server.configCwd == nil)
    }

    // MARK: - Disabled Flag Tests

    @Test("disabled flag defaults to false")
    func disabledDefaultsFalse() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        #expect(server.disabled == false)
    }

    @Test("pending config removal defaults to false")
    func pendingConfigRemovalDefaultsFalse() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .config)

        #expect(server.isPendingConfigRemoval == false)
    }

    @Test("pending config removal flag can be toggled")
    func pendingConfigRemovalCanBeToggled() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .config)

        server.isPendingConfigRemoval = true
        #expect(server.isPendingConfigRemoval == true)

        server.isPendingConfigRemoval = false
        #expect(server.isPendingConfigRemoval == false)
    }

    @Test("disabled flag can be set to true")
    func disabledCanBeSetTrue() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        server.disabled = true

        #expect(server.disabled == true)
    }

    @Test("disabled flag can be toggled")
    func disabledCanBeToggled() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        server.disabled = true
        #expect(server.disabled == true)

        server.disabled = false
        #expect(server.disabled == false)

        server.disabled = true
        #expect(server.disabled == true)
    }

    // MARK: - Synthetic Server Tests

    @Test("Synthetic source can be used")
    func syntheticSourceCanBeUsed() {
        let manifest = makeManifest(name: "shipyard")
        let server = MCPServer(manifest: manifest, source: .synthetic)

        #expect(server.source == .synthetic)
        #expect(server.manifest.name == "shipyard")
    }

    // MARK: - Source Combinations with Transport

    @Test("Manifest source with HTTP transport")
    func manifestSourceWithHTTPTransport() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .manifest, transport: .streamableHTTP)

        #expect(server.source == .manifest)
        #expect(server.transport == .streamableHTTP)
        #expect(server.isHTTP == true)
    }

    @Test("Synthetic source with stdio transport")
    func syntheticSourceWithStdioTransport() {
        let manifest = makeManifest(name: "shipyard")
        let server = MCPServer(manifest: manifest, source: .synthetic, transport: .stdio)

        #expect(server.source == .synthetic)
        #expect(server.transport == .stdio)
        #expect(server.isHTTP == false)
    }

    // MARK: - State and Disabled Interaction Tests

    @Test("Disabled server starts in idle state")
    func disabledServerInIdleState() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)
        server.disabled = true

        #expect(server.state == .idle)
    }

    @Test("disabled flag is independent of state")
    func disabledIndependentOfState() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest)

        server.disabled = true
        server.state = .starting
        #expect(server.disabled == true)
        #expect(server.state == .starting)

        server.state = .error("test error")
        #expect(server.disabled == true)
        #expect(!server.state.isRunning)
    }

    // MARK: - Property Immutability Tests

    @Test("source property is nonisolated (read-only after init)")
    func sourcePropertyNonisolated() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, source: .config)

        // Source is immutable after construction
        #expect(server.source == .config)
    }

    @Test("transport property is nonisolated (read-only after init)")
    func transportPropertyNonisolated() {
        let manifest = makeManifest()
        let server = MCPServer(manifest: manifest, transport: .streamableHTTP)

        // Transport is immutable after construction
        #expect(server.transport == .streamableHTTP)
    }

    // MARK: - Multiple Servers Comparison Tests

    @Test("Different sources can be compared")
    func differentSourcesCanBeCompared() {
        let manifest = makeManifest()

        let manifestServer = MCPServer(manifest: manifest, source: .manifest)
        let configServer = MCPServer(manifest: manifest, source: .config)
        let syntheticServer = MCPServer(manifest: manifest, source: .synthetic)

        #expect(manifestServer.source == .manifest)
        #expect(configServer.source == .config)
        #expect(syntheticServer.source == .synthetic)

        #expect(manifestServer.source != configServer.source)
        #expect(configServer.source != syntheticServer.source)
    }

    @Test("Different transports can be compared")
    func differentTransportsCanBeCompared() {
        let manifest = makeManifest()

        let stdioServer = MCPServer(manifest: manifest, transport: .stdio)
        let httpServer = MCPServer(manifest: manifest, transport: .streamableHTTP)

        #expect(stdioServer.transport == .stdio)
        #expect(httpServer.transport == .streamableHTTP)

        #expect(stdioServer.transport != httpServer.transport)
        #expect(stdioServer.isHTTP != httpServer.isHTTP)
    }

    // MARK: - Codability Tests

    @Test("MCPSource Codable: manifest")
    func mcpSourceCodableManifest() throws {
        let source = MCPSource.manifest
        let encoder = JSONEncoder()
        let data = try encoder.encode(source)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(MCPSource.self, from: data)

        #expect(decoded == .manifest)
    }

    @Test("MCPSource Codable: config")
    func mcpSourceCodableConfig() throws {
        let source = MCPSource.config
        let encoder = JSONEncoder()
        let data = try encoder.encode(source)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(MCPSource.self, from: data)

        #expect(decoded == .config)
    }

    @Test("MCPSource Codable: synthetic")
    func mcpSourceCodableSynthetic() throws {
        let source = MCPSource.synthetic
        let encoder = JSONEncoder()
        let data = try encoder.encode(source)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(MCPSource.self, from: data)

        #expect(decoded == .synthetic)
    }

    @Test("MCPTransport Codable: stdio")
    func mcpTransportCodableStdio() throws {
        let transport = MCPTransport.stdio
        let encoder = JSONEncoder()
        let data = try encoder.encode(transport)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(MCPTransport.self, from: data)

        #expect(decoded == .stdio)
    }

    @Test("MCPTransport Codable: streamableHTTP")
    func mcpTransportCodableStreamableHTTP() throws {
        let transport = MCPTransport.streamableHTTP
        let encoder = JSONEncoder()
        let data = try encoder.encode(transport)
        let decoder = JSONDecoder()
        let decoded = try decoder.decode(MCPTransport.self, from: data)

        #expect(decoded == .streamableHTTP)
    }

    // MARK: - ID and Hashable Tests

    @Test("Each server has unique ID")
    func eachServerHasUniqueID() {
        let manifest = makeManifest()

        let server1 = MCPServer(manifest: manifest, source: .config)
        let server2 = MCPServer(manifest: manifest, source: .config)

        #expect(server1.id != server2.id)
    }

    @Test("Servers are hashable and can be used in sets")
    func serversHashableInSets() {
        let manifest = makeManifest()

        let server1 = MCPServer(manifest: manifest, source: .config)
        let server2 = MCPServer(manifest: manifest, source: .manifest)

        var serverSet = Set<MCPServer>()
        serverSet.insert(server1)
        serverSet.insert(server2)

        #expect(serverSet.count == 2)
        #expect(serverSet.contains(server1))
        #expect(serverSet.contains(server2))
    }

    @Test("Server equality based on ID")
    func serverEqualityBasedOnID() {
        let manifest = makeManifest()

        let server1 = MCPServer(manifest: manifest, source: .config)
        let server2 = server1  // Same instance

        #expect(server1 == server2)
    }
}
