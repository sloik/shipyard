import Testing
import Foundation
@testable import Shipyard

@Suite("MCPRegistry Config Loading")
@MainActor
struct MCPRegistryConfigTests {

    // MARK: - Helper Methods

    private func makeConfigPath() -> String {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("mcps-\(UUID().uuidString).json")
            .path
    }

    private func writeConfig(_ json: String, to path: String) throws {
        try json.write(to: URL(fileURLWithPath: path), atomically: true, encoding: .utf8)
    }

    private func makeMigrationLogPath() -> String {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("manifest-migration-log-\(UUID().uuidString).json")
            .path
    }

    private func makeManifest(name: String = "manifest-server") -> MCPManifest {
        let json = """
        {
            "name": "\(name)",
            "version": "1.0.0",
            "description": "Test manifest server",
            "transport": "stdio",
            "command": "python3",
            "args": ["server.py"]
        }
        """.data(using: .utf8)!
        return try! JSONDecoder().decode(MCPManifest.self, from: json)
    }

    private func makeMCPConfig(with entries: [String: [String: Any]]) throws -> MCPConfig {
        let json = try JSONSerialization.data(withJSONObject: ["mcpServers": entries])
        return try JSONDecoder().decode(MCPConfig.self, from: json)
    }

    // MARK: - Config to MCPServer Creation Tests

    @Test("Config entry with stdio creates MCPServer with .config source")
    func stdioConfigCreatesConfigSourceServer() throws {
        let config = try makeMCPConfig(with: [
            "stdio-server": [
                "command": "python3",
                "args": ["server.py"]
            ]
        ])

        let entry = try #require(config.mcpServers["stdio-server"])

        // Verify entry can be converted to MCPServer
        #expect(entry.command == "python3")
        #expect(entry.args == ["server.py"])
        #expect(entry.transport == nil)  // Omitted defaults to stdio
    }

    @Test("Config entry with HTTP creates MCPServer with .streamableHTTP transport")
    func httpConfigCreatesHTTPTransportServer() throws {
        let config = try makeMCPConfig(with: [
            "http-server": [
                "transport": "streamable-http",
                "url": "https://api.example.com/mcp"
            ]
        ])

        let entry = try #require(config.mcpServers["http-server"])

        #expect(entry.transport == "streamable-http")
        #expect(entry.url == "https://api.example.com/mcp")
    }

    @Test("Registry can register both manifest and config sources")
    func registryAcceptsBothSources() throws {
        let registry = MCPRegistry()

        let manifestServer = MCPServer(manifest: makeManifest(name: "manifest-srv"), source: .manifest)
        let configServer = MCPServer(manifest: makeManifest(name: "config-srv"), source: .config)

        try registry.register(manifestServer)
        try registry.register(configServer)

        #expect(registry.registeredServers.count == 2)
        #expect(registry.registeredServers[0].source == .manifest)
        #expect(registry.registeredServers[1].source == .config)
    }

    // MARK: - Name Collision Tests

    @Test("Name collision: manifest source registered first, config tries to register same name")
    func nameCollisionManifestVsConfig() throws {
        let registry = MCPRegistry()

        // Register manifest server first
        let manifestServer = MCPServer(manifest: makeManifest(name: "shared"), source: .manifest)
        try registry.register(manifestServer)

        #expect(registry.registeredServers.count == 1)
        #expect(registry.registeredServers[0].source == .manifest)

        // Try to register config server with same name (should follow registry's dedup logic)
        let configServer = MCPServer(manifest: makeManifest(name: "shared"), source: .config)
        #expect(throws: RegistryError.self) {
            try registry.register(configServer)
        }

        // Should still have only manifest version
        #expect(registry.registeredServers.count == 1)
        #expect(registry.registeredServers[0].source == .manifest)
    }

    @Test("Override flag allows config to replace manifest")
    func overrideFlagUsedInLoadingLogic() throws {
        let config = try makeMCPConfig(with: [
            "override-test": [
                "command": "node",
                "override": true
            ]
        ])

        let entry = try #require(config.mcpServers["override-test"])
        #expect(entry.override == true)
        #expect(entry.command == "node")
    }

    // MARK: - Disabled Flag Tests

    @Test("disabled flag in config is preserved in MCPServer")
    func disabledFlagPreserved() throws {
        let config = try makeMCPConfig(with: [
            "disabled-server": [
                "command": "python3",
                "disabled": true
            ]
        ])

        let entry = try #require(config.mcpServers["disabled-server"])
        #expect(entry.disabled == true)

        // This flag should be transferred to MCPServer.disabled on creation
    }

    @Test("disabled: false explicitly set")
    func disabledExplicitlyFalse() throws {
        let config = try makeMCPConfig(with: [
            "enabled-server": [
                "command": "python3",
                "disabled": false
            ]
        ])

        let entry = try #require(config.mcpServers["enabled-server"])
        #expect(entry.disabled == false)
    }

    @Test("disabled defaults to nil when omitted")
    func disabledDefaultsNil() throws {
        let config = try makeMCPConfig(with: [
            "normal-server": [
                "command": "python3"
            ]
        ])

        let entry = try #require(config.mcpServers["normal-server"])
        #expect(entry.disabled == nil)
    }

    // MARK: - Transport Determination Tests

    @Test("transport field determines MCPTransport type")
    func transportDeterminationType() throws {
        let config = try makeMCPConfig(with: [
            "stdio-explicit": [
                "transport": "stdio",
                "command": "python3"
            ],
            "http": [
                "transport": "streamable-http",
                "url": "https://api.example.com"
            ],
            "stdio-default": [
                "command": "node"
            ]
        ])

        let stdioExplicit = try #require(config.mcpServers["stdio-explicit"])
        #expect(stdioExplicit.transport == "stdio")

        let http = try #require(config.mcpServers["http"])
        #expect(http.transport == "streamable-http")

        let stdioDefault = try #require(config.mcpServers["stdio-default"])
        #expect(stdioDefault.transport == nil)  // Defaults to stdio
    }

    // MARK: - CWD Tests

    @Test("cwd field is preserved in config entry")
    func cwdFieldPreserved() throws {
        let config = try makeMCPConfig(with: [
            "with-cwd": [
                "command": "python3",
                "cwd": "/tmp/mock-my-mcp"
            ]
        ])

        let entry = try #require(config.mcpServers["with-cwd"])
        #expect(entry.cwd == "/tmp/mock-my-mcp")
    }

    @Test("cwd can be transferred to MCPServer.configCwd")
    func cwdTransferredToServer() {
        let server = MCPServer(manifest: makeManifest(), source: .config)
        server.configCwd = "/tmp/mock-my-mcp"

        #expect(server.configCwd == "/tmp/mock-my-mcp")
    }

    // MARK: - Environment Tests

    @Test("env field with multiple variables")
    func multipleEnvVariables() throws {
        let config = try makeMCPConfig(with: [
            "env-server": [
                "command": "python3",
                "env": [
                    "API_KEY": "mock-api-key",
                    "PYTHONUNBUFFERED": "1",
                    "CUSTOM_VAR": "custom-value"
                ]
            ]
        ])

        let entry = try #require(config.mcpServers["env-server"])
        let env = try #require(entry.env)

        #expect(env["API_KEY"] == "mock-api-key")
        #expect(env["PYTHONUNBUFFERED"] == "1")
        #expect(env["CUSTOM_VAR"] == "custom-value")
    }

    @Test("env can be nil")
    func envCanBeNil() throws {
        let config = try makeMCPConfig(with: [
            "no-env": [
                "command": "python3"
            ]
        ])

        let entry = try #require(config.mcpServers["no-env"])
        #expect(entry.env == nil)
    }

    // MARK: - Secret Keys Tests

    @Test("env_secret_keys field preserved")
    func envSecretKeysPreserved() throws {
        let config = try makeMCPConfig(with: [
            "secrets": [
                "command": "python3",
                "env": ["API_TOKEN": "secret"],
                "env_secret_keys": ["API_TOKEN"]
            ]
        ])

        let entry = try #require(config.mcpServers["secrets"])
        #expect(entry.envSecretKeys == ["API_TOKEN"])
    }

    @Test("headers_secret_keys field preserved")
    func headersSecretKeysPreserved() throws {
        let config = try makeMCPConfig(with: [
            "http-secrets": [
                "transport": "streamable-http",
                "url": "https://api.example.com",
                "headers": ["Authorization": "Bearer token"],
                "headers_secret_keys": ["Authorization"]
            ]
        ])

        let entry = try #require(config.mcpServers["http-secrets"])
        #expect(entry.headersSecretKeys == ["Authorization"])
    }

    // MARK: - Headers Tests

    @Test("headers field with auth and custom headers")
    func headersMultiple() throws {
        let config = try makeMCPConfig(with: [
            "http-headers": [
                "transport": "streamable-http",
                "url": "https://api.example.com",
                "headers": [
                    "Authorization": "Bearer tok-123",
                    "X-Custom-Header": "custom-value",
                    "Accept": "application/json"
                ]
            ]
        ])

        let entry = try #require(config.mcpServers["http-headers"])
        let headers = try #require(entry.headers)

        #expect(headers["Authorization"] == "Bearer tok-123")
        #expect(headers["X-Custom-Header"] == "custom-value")
        #expect(headers["Accept"] == "application/json")
    }

    // MARK: - Validation Integration Tests

    @Test("Server finds validation errors in config")
    func validationIntegration() throws {
        // Create config with validation errors
        let config = try makeMCPConfig(with: [
            "no-command": [
                "transport": "stdio"
                // Missing required command
            ],
            "no-url": [
                "transport": "streamable-http"
                // Missing required url
            ]
        ])

        let errors = config.validate()

        #expect(errors.count >= 2)
        #expect(errors.contains { $0.contains("no-command") && $0.contains("command") })
        #expect(errors.contains { $0.contains("no-url") && $0.contains("url") })
    }

    @Test("Registry server method finds by name")
    func registryFindsByName() throws {
        let registry = MCPRegistry()

        let server1 = MCPServer(manifest: makeManifest(name: "server-1"), source: .config)
        let server2 = MCPServer(manifest: makeManifest(name: "server-2"), source: .config)

        try registry.register(server1)
        try registry.register(server2)

        #expect(registry.server(named: "server-1") != nil)
        #expect(registry.server(named: "server-2") != nil)
        #expect(registry.server(named: "nonexistent") == nil)
    }

    // MARK: - Config + Manifest Integration Tests

    @Test("Both manifest and config servers coexist")
    func coexistenceBySource() throws {
        let registry = MCPRegistry()

        let manifestSrv = MCPServer(manifest: makeManifest(name: "from-manifest"), source: .manifest)
        let configSrv = MCPServer(manifest: makeManifest(name: "from-config"), source: .config)

        try registry.register(manifestSrv)
        try registry.register(configSrv)

        let allServers = registry.registeredServers
        #expect(allServers.count == 2)

        let byManifest = allServers.filter { $0.source == .manifest }
        let byConfig = allServers.filter { $0.source == .config }

        #expect(byManifest.count == 1)
        #expect(byConfig.count == 1)
    }

    // MARK: - Edge Cases

    @Test("Empty mcpServers in config")
    func emptyMcpServersOk() throws {
        let config = try makeMCPConfig(with: [:])

        #expect(config.mcpServers.isEmpty)
    }

    @Test("Config entry name with special characters")
    func nameWithSpecialCharacters() throws {
        let config = try makeMCPConfig(with: [
            "my-mcp-server_2": [
                "command": "python3"
            ]
        ])

        let entry = try #require(config.mcpServers["my-mcp-server_2"])
        #expect(entry.command == "python3")
    }

    // MARK: - BUG-012: Case-Insensitive Name Collision Tests (AC2, AC3)

    @Test("Case-insensitive name collision: config 'shipyard' collides with manifest 'Shipyard'")
    func caseInsensitiveCollisionShipyard() throws {
        let registry = MCPRegistry()

        // Register manifest server with uppercase name
        let manifestServer = MCPServer(manifest: makeManifest(name: "Shipyard"), source: .manifest)
        try registry.register(manifestServer)

        #expect(registry.registeredServers.count == 1)
        #expect(registry.registeredServers[0].manifest.name == "Shipyard")

        // Try to register config server with lowercase name (should be blocked)
        let configServer = MCPServer(manifest: makeManifest(name: "shipyard"), source: .config)
        #expect(throws: RegistryError.self) {
            try registry.register(configServer)
        }

        // Should still have only manifest version
        #expect(registry.registeredServers.count == 1)
        #expect(registry.registeredServers[0].manifest.name == "Shipyard")
    }

    @Test("Case-insensitive name collision: config entry can override manifest (with override flag)")
    func caseInsensitiveCollisionWithOverride() throws {
        let config = try makeMCPConfig(with: [
            "MyServer": [
                "command": "node",
                "override": true
            ]
        ])

        let entry = try #require(config.mcpServers["MyServer"])
        #expect(entry.override == true)
        #expect(entry.command == "node")
    }

    @Test("Case-insensitive dedup: existing 'LowerCaseServer' blocks config 'lowercaseserver'")
    func caseInsensitiveDedup() throws {
        let registry = MCPRegistry()

        // Register manifest server with mixed case
        let manifestServer = MCPServer(manifest: makeManifest(name: "LowerCaseServer"), source: .manifest)
        try registry.register(manifestServer)

        // Try to register config server with different case (should be blocked)
        let configServer = MCPServer(manifest: makeManifest(name: "lowercaseserver"), source: .config)
        #expect(throws: RegistryError.self) {
            try registry.register(configServer)
        }

        #expect(registry.registeredServers.count == 1)
        #expect(registry.registeredServers[0].manifest.name == "LowerCaseServer")
    }

    @Test("Config-sourced stdio MCP with cwd sets rootDirectory")
    func configStdioWithCwdSetsRootDirectory() throws {
        // This test verifies that when a config entry has a cwd, it gets set as rootDirectory
        let config = try makeMCPConfig(with: [
            "server-with-cwd": [
                "command": "python3",
                "args": ["server.py"],
                "cwd": "/tmp/mock-my-mcp"
            ]
        ])

        let entry = try #require(config.mcpServers["server-with-cwd"])
        #expect(entry.cwd == "/tmp/mock-my-mcp")
        #expect(entry.command == "python3")

        // Verify manifest can be created with cwd info
        let manifest = MCPManifest(
            name: "server-with-cwd",
            version: "config",
            description: "Test server",
            transport: "stdio",
            command: entry.command ?? "",
            args: entry.args ?? [],
            env: entry.env,
            env_secret_keys: entry.envSecretKeys,
            dependencies: nil,
            health_check: nil,
            logging: nil,
            install: nil
        )

        // rootDirectory should be settable via setRootDirectory
        var settableManifest = manifest
        settableManifest.setRootDirectory(URL(fileURLWithPath: "/tmp/mock-my-mcp"))

        #expect(settableManifest.rootDirectory != nil)
        #expect(settableManifest.rootDirectory?.path == "/tmp/mock-my-mcp")
    }

    // MARK: - SPEC-019 Pending Removal Behavior

    @Test("Reload removes idle config server immediately when entry is deleted")
    func reloadRemovesIdleConfigServerImmediately() async throws {
        let configPath = makeConfigPath()
        defer { try? FileManager.default.removeItem(atPath: configPath) }

        let registry = MCPRegistry()
        let server = MCPServer(manifest: makeManifest(name: "gone-idle"), source: .config)
        try registry.register(server)

        try writeConfig("""
        {
          "mcpServers": {}
        }
        """, to: configPath)

        await registry.reloadConfig(from: configPath)

        #expect(registry.registeredServers.isEmpty)
    }

    @Test("Reload keeps running config server as pending removal when entry is deleted")
    func reloadKeepsRunningConfigServerPendingRemoval() async throws {
        let configPath = makeConfigPath()
        defer { try? FileManager.default.removeItem(atPath: configPath) }

        let registry = MCPRegistry()
        let server = MCPServer(manifest: makeManifest(name: "gone-running"), source: .config)
        server.state = .running
        try registry.register(server)

        try writeConfig("""
        {
          "mcpServers": {}
        }
        """, to: configPath)

        await registry.reloadConfig(from: configPath)

        #expect(registry.registeredServers.count == 1)
        #expect(registry.registeredServers[0].manifest.name == "gone-running")
        #expect(server.isPendingConfigRemoval == true)
        #expect(server.configNeedsRestart == false)
    }

    @Test("Pending removal server is unregistered after stop cleanup")
    func pendingRemovalServerIsUnregisteredAfterStopCleanup() throws {
        let registry = MCPRegistry()
        let server = MCPServer(manifest: makeManifest(name: "stop-me"), source: .config)
        server.isPendingConfigRemoval = true
        try registry.register(server)

        registry.removeServerIfPendingConfigRemoval(server)

        #expect(registry.registeredServers.isEmpty)
    }

    @Test("Reload clears pending removal when config entry is restored")
    func reloadClearsPendingRemovalWhenConfigReturns() async throws {
        let configPath = makeConfigPath()
        defer { try? FileManager.default.removeItem(atPath: configPath) }

        let registry = MCPRegistry()
        let server = MCPServer(manifest: makeManifest(name: "restored-server"), source: .config)
        server.state = .running
        server.isPendingConfigRemoval = true
        try registry.register(server)

        try writeConfig("""
        {
          "mcpServers": {
            "restored-server": {
              "command": "python3",
              "args": ["server.py"]
            }
          }
        }
        """, to: configPath)

        await registry.reloadConfig(from: configPath)

        #expect(registry.registeredServers.count == 1)
        #expect(server.isPendingConfigRemoval == false)
    }

    @Test("Config-only hear-me-say load writes migration log and keeps config source")
    func hearMeSayConfigLoadPersistsMigrationLog() async throws {
        let configPath = makeConfigPath()
        let migrationLogPath = makeMigrationLogPath()
        defer {
            try? FileManager.default.removeItem(atPath: configPath)
            try? FileManager.default.removeItem(atPath: migrationLogPath)
        }

        try writeConfig("""
        {
          "mcpServers": {
            "hear-me-say": {
              "transport": "stdio",
              "command": "python3",
              "args": ["server.py"],
              "cwd": "/tmp/hear-me-say",
              "env": {
                "PYTHONUNBUFFERED": "1"
              },
              "migrated_from": "/tmp/hear-me-say"
            }
          }
        }
        """, to: configPath)

        let registry = MCPRegistry()
        registry.setManifestDiscoveryReadOnly(true)

        await registry.loadConfig(from: configPath, migrationLogPath: migrationLogPath)

        #expect(registry.registeredServers.count == 1)
        let server = try #require(registry.registeredServers.first)
        #expect(server.manifest.name == "hear-me-say")
        #expect(server.source == .config)
        #expect(server.manifest.command == "python3")
        #expect(server.manifest.args == ["server.py"])
        #expect(server.manifest.env == ["PYTHONUNBUFFERED": "1"])
        #expect(server.configCwd == "/tmp/hear-me-say")
        #expect(server.migratedFrom == "/tmp/hear-me-say")

        let migrationLog = try MCPConfig.MigrationLog.loadOrCreateDefault(at: migrationLogPath)
        let hearMeSay = try #require(migrationLog.entries["hear-me-say"])
        #expect(hearMeSay.name == "hear-me-say")
        #expect(hearMeSay.source == "config")
        #expect(hearMeSay.command == "python3")
        #expect(hearMeSay.args == ["server.py"])
        #expect(hearMeSay.cwd == "/tmp/hear-me-say")
        #expect(hearMeSay.env == ["PYTHONUNBUFFERED": "1"])
        #expect(hearMeSay.migratedFrom == "/tmp/hear-me-say")
    }

    @Test("Config-only lmac-run load writes migration log and keeps config source")
    func lmacRunConfigLoadPersistsMigrationLog() async throws {
        let configPath = makeConfigPath()
        let migrationLogPath = makeMigrationLogPath()
        defer {
            try? FileManager.default.removeItem(atPath: configPath)
            try? FileManager.default.removeItem(atPath: migrationLogPath)
        }

        try writeConfig("""
        {
          "mcpServers": {
            "lmac-run": {
              "transport": "stdio",
              "command": ".venv/bin/python",
              "args": ["server.py"],
              "cwd": "/tmp/lmac-run-mcp",
              "env": {
                "PYTHONUNBUFFERED": "1"
              },
              "migrated_from": "/tmp/lmac-run-mcp"
            }
          }
        }
        """, to: configPath)

        let registry = MCPRegistry()
        registry.setManifestDiscoveryReadOnly(true)

        await registry.loadConfig(from: configPath, migrationLogPath: migrationLogPath)

        #expect(registry.registeredServers.count == 1)
        let server = try #require(registry.registeredServers.first)
        #expect(server.manifest.name == "lmac-run")
        #expect(server.source == .config)
        #expect(server.manifest.command == ".venv/bin/python")
        #expect(server.manifest.args == ["server.py"])
        #expect(server.manifest.env == ["PYTHONUNBUFFERED": "1"])
        #expect(server.configCwd == "/tmp/lmac-run-mcp")
        #expect(server.migratedFrom == "/tmp/lmac-run-mcp")

        let migrationLog = try MCPConfig.MigrationLog.loadOrCreateDefault(at: migrationLogPath)
        let lmacRun = try #require(migrationLog.entries["lmac-run"])
        #expect(lmacRun.name == "lmac-run")
        #expect(lmacRun.source == "config")
        #expect(lmacRun.command == ".venv/bin/python")
        #expect(lmacRun.args == ["server.py"])
        #expect(lmacRun.cwd == "/tmp/lmac-run-mcp")
        #expect(lmacRun.env == ["PYTHONUNBUFFERED": "1"])
        #expect(lmacRun.migratedFrom == "/tmp/lmac-run-mcp")
    }

    @Test("Config-only lmstudio load writes migration log and keeps config source")
    func lmstudioConfigLoadPersistsMigrationLog() async throws {
        let configPath = makeConfigPath()
        let migrationLogPath = makeMigrationLogPath()
        defer {
            try? FileManager.default.removeItem(atPath: configPath)
            try? FileManager.default.removeItem(atPath: migrationLogPath)
        }

        try writeConfig("""
        {
          "mcpServers": {
            "lmstudio": {
              "transport": "stdio",
              "command": "python3",
              "args": ["server.py"],
              "cwd": "/tmp/lmstudio-mcp",
              "env": {
                "PYTHONUNBUFFERED": "1",
                "LM_STUDIO_BASE": "http://localhost:1234",
                "LM_STUDIO_TIMEOUT": "120"
              },
              "env_secret_keys": ["LM_STUDIO_TOKEN"],
              "migrated_from": "/tmp/lmstudio-mcp"
            }
          }
        }
        """, to: configPath)

        let registry = MCPRegistry()
        registry.setManifestDiscoveryReadOnly(true)

        await registry.loadConfig(from: configPath, migrationLogPath: migrationLogPath)

        #expect(registry.registeredServers.count == 1)
        let server = try #require(registry.registeredServers.first)
        #expect(server.manifest.name == "lmstudio")
        #expect(server.source == .config)
        #expect(server.manifest.command == "python3")
        #expect(server.manifest.args == ["server.py"])
        #expect(server.manifest.env == [
            "PYTHONUNBUFFERED": "1",
            "LM_STUDIO_BASE": "http://localhost:1234",
            "LM_STUDIO_TIMEOUT": "120"
        ])
        #expect(server.configCwd == "/tmp/lmstudio-mcp")
        #expect(server.configEnvSecretKeys == ["LM_STUDIO_TOKEN"])
        #expect(server.migratedFrom == "/tmp/lmstudio-mcp")

        let migrationLog = try MCPConfig.MigrationLog.loadOrCreateDefault(at: migrationLogPath)
        let lmstudio = try #require(migrationLog.entries["lmstudio"])
        #expect(lmstudio.name == "lmstudio")
        #expect(lmstudio.source == "config")
        #expect(lmstudio.command == "python3")
        #expect(lmstudio.args == ["server.py"])
        #expect(lmstudio.cwd == "/tmp/lmstudio-mcp")
        #expect(lmstudio.env == [
            "PYTHONUNBUFFERED": "1",
            "LM_STUDIO_BASE": "http://localhost:1234",
            "LM_STUDIO_TIMEOUT": "120"
        ])
        #expect(lmstudio.envSecretKeys == ["LM_STUDIO_TOKEN"])
        #expect(lmstudio.migratedFrom == "/tmp/lmstudio-mcp")
    }
}
