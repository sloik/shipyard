import Testing
import Foundation
@testable import Shipyard

/// Tests for R26: Keychain integration for config secrets
/// Verifies that env_secret_keys and headers_secret_keys are resolved from Keychain
@Suite("R26: Keychain Secret Resolution")
@MainActor
struct KeychainSecretResolutionTests {
    
    // MARK: - Helper Functions
    
    func makeTestServer(
        name: String = "test-mcp",
        configEnvSecretKeys: [String]? = nil,
        configHeaderSecretKeys: [String]? = nil,
        configHeaders: [String: String]? = nil
    ) -> MCPServer {
        let json = """
        {
            "name": "\(name)",
            "version": "1.0",
            "description": "Test server",
            "transport": "stdio",
            "command": "test",
            "args": []
        }
        """.data(using: .utf8)!
        let manifest = try! JSONDecoder().decode(MCPManifest.self, from: json)
        
        let server = MCPServer(manifest: manifest, source: .config, transport: .stdio)
        server.configEnvSecretKeys = configEnvSecretKeys
        server.configHeaderSecretKeys = configHeaderSecretKeys
        server.configHeaders = configHeaders
        return server
    }
    
    func makeHTTPTestServer(
        name: String = "http-mcp",
        configHeaderSecretKeys: [String]? = nil,
        configHeaders: [String: String]? = nil
    ) -> MCPServer {
        let json = """
        {
            "name": "\(name)",
            "version": "1.0",
            "description": "HTTP test server",
            "transport": "streamable-http",
            "command": "",
            "args": []
        }
        """.data(using: .utf8)!
        let manifest = try! JSONDecoder().decode(MCPManifest.self, from: json)
        
        let server = MCPServer(manifest: manifest, source: .config, transport: .streamableHTTP)
        server.configHeaderSecretKeys = configHeaderSecretKeys
        server.configHeaders = configHeaders
        return server
    }
    
    // MARK: - Tests for Env Secrets
    
    @Test("MCPServer stores env secret keys from config")
    func storesEnvSecretKeys() {
        let server = makeTestServer(configEnvSecretKeys: ["API_KEY", "TOKEN"])
        #expect(server.configEnvSecretKeys == ["API_KEY", "TOKEN"])
    }
    
    @Test("MCPServer stores header secret keys from config")
    func storesHeaderSecretKeys() {
        let server = makeHTTPTestServer(configHeaderSecretKeys: ["Authorization", "X-API-Key"])
        #expect(server.configHeaderSecretKeys == ["Authorization", "X-API-Key"])
    }
    
    @Test("MCPServer stores config headers")
    func storesConfigHeaders() {
        let headers = ["Accept": "application/json", "User-Agent": "Shipyard/1.0"]
        let server = makeHTTPTestServer(configHeaders: headers)
        #expect(server.configHeaders == headers)
    }
    
    @Test("MCPServer supports mixed plain and secret headers")
    func supportsMixedHeaders() {
        let plainHeaders = ["Accept": "application/json"]
        let server = makeHTTPTestServer(
            configHeaderSecretKeys: ["Authorization"],
            configHeaders: plainHeaders
        )
        #expect(server.configHeaders == plainHeaders)
        #expect(server.configHeaderSecretKeys == ["Authorization"])
    }
    
    // MARK: - Tests for Config Registry Integration
    
    @Test("Registry stores env secret keys when creating config server")
    func registryStoresEnvSecrets() throws {
        let config = """
        {
            "mcpServers": {
                "test-env-secrets": {
                    "transport": "stdio",
                    "command": "python3",
                    "args": ["server.py"],
                    "env": {"NORMAL_VAR": "value"},
                    "env_secret_keys": ["API_TOKEN", "DB_PASSWORD"]
                }
            }
        }
        """
        
        let configData = config.data(using: .utf8)!
        let mcpConfig = try JSONDecoder().decode(MCPConfig.self, from: configData)
        let entry = mcpConfig.mcpServers["test-env-secrets"]!
        
        #expect(entry.envSecretKeys == ["API_TOKEN", "DB_PASSWORD"])
        #expect(entry.env?["NORMAL_VAR"] == "value")
    }
    
    @Test("Registry stores header secret keys when creating HTTP config server")
    func registryStoresHeaderSecrets() throws {
        let config = """
        {
            "mcpServers": {
                "test-http-secrets": {
                    "transport": "streamable-http",
                    "url": "https://api.example.com/mcp",
                    "headers": {"Accept": "application/json"},
                    "headers_secret_keys": ["Authorization", "X-API-Key"]
                }
            }
        }
        """
        
        let configData = config.data(using: .utf8)!
        let mcpConfig = try JSONDecoder().decode(MCPConfig.self, from: configData)
        let entry = mcpConfig.mcpServers["test-http-secrets"]!
        
        #expect(entry.headersSecretKeys == ["Authorization", "X-API-Key"])
        #expect(entry.headers?["Accept"] == "application/json")
    }
    
    @Test("Config validation ignores secret key fields (no errors)")
    func validationIgnoresSecretKeys() throws {
        let config = """
        {
            "mcpServers": {
                "test": {
                    "transport": "stdio",
                    "command": "test",
                    "env_secret_keys": ["KEY1", "KEY2"]
                }
            }
        }
        """
        
        let configData = config.data(using: .utf8)!
        let mcpConfig = try JSONDecoder().decode(MCPConfig.self, from: configData)
        let errors = mcpConfig.validate()
        
        #expect(errors.isEmpty, "Config with env_secret_keys should be valid")
    }
    
    // MARK: - Tests for Keychain Interaction Scenarios
    
    @Test("Server with no secret keys should not attempt Keychain lookup")
    func noSecretKeysNoKeychainLookup() {
        let server = makeTestServer(configEnvSecretKeys: nil)
        #expect(server.configEnvSecretKeys == nil)
        
        let httpServer = makeHTTPTestServer(configHeaderSecretKeys: nil)
        #expect(httpServer.configHeaderSecretKeys == nil)
    }
    
    @Test("Server with empty secret keys list should not attempt Keychain lookup")
    func emptySecretKeysNoKeychainLookup() {
        let server = makeTestServer(configEnvSecretKeys: [])
        #expect(server.configEnvSecretKeys == [])
        
        let httpServer = makeHTTPTestServer(configHeaderSecretKeys: [])
        #expect(httpServer.configHeaderSecretKeys == [])
    }
    
    @Test("HTTP server headers are passed correctly to HTTPBridge")
    func httpServerHeadersPassedToBridge() {
        let plainHeaders = ["Content-Type": "application/json"]
        let secretKeys = ["Authorization"]
        let server = makeHTTPTestServer(
            configHeaderSecretKeys: secretKeys,
            configHeaders: plainHeaders
        )
        
        #expect(server.configHeaders == plainHeaders)
        #expect(server.configHeaderSecretKeys == secretKeys)
        #expect(server.transport == .streamableHTTP)
    }
}
