import Testing
import Foundation
@testable import Shipyard

@Suite("MCPConfig")
struct MCPConfigTests {

    // MARK: - Decoding Tests

    @Test("Decodes valid full config with stdio and HTTP entries")
    func decodesValidFullConfig() throws {
        let json = """
        {
          "mcpServers": {
            "my-python-mcp": {
              "transport": "stdio",
              "command": "/opt/homebrew/bin/python3",
              "args": ["server.py"],
              "cwd": "/tmp/mock-my-mcp",
              "env": {
                "API_KEY": "mock-api-key",
                "PYTHONUNBUFFERED": "1"
              },
              "env_secret_keys": ["API_KEY"],
              "disabled": false,
              "override": false
            },
            "remote-api": {
              "transport": "streamable-http",
              "url": "https://api.example.com/mcp",
              "headers": {
                "Authorization": "Bearer tok-456"
              },
              "headers_secret_keys": ["Authorization"]
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)

        // Check stdio entry
        let stdioEntry = try #require(config.mcpServers["my-python-mcp"])
        #expect(stdioEntry.transport == "stdio")
        #expect(stdioEntry.command == "/opt/homebrew/bin/python3")
        #expect(stdioEntry.args == ["server.py"])
        #expect(stdioEntry.cwd == "/tmp/mock-my-mcp")
        #expect(stdioEntry.env?["API_KEY"] == "mock-api-key")
        #expect(stdioEntry.env?["PYTHONUNBUFFERED"] == "1")
        #expect(stdioEntry.envSecretKeys == ["API_KEY"])
        #expect(stdioEntry.disabled == false)
        #expect(stdioEntry.override == false)

        // Check HTTP entry
        let httpEntry = try #require(config.mcpServers["remote-api"])
        #expect(httpEntry.transport == "streamable-http")
        #expect(httpEntry.url == "https://api.example.com/mcp")
        #expect(httpEntry.headers?["Authorization"] == "Bearer tok-456")
        #expect(httpEntry.headersSecretKeys == ["Authorization"])
    }

    @Test("Decodes minimal config with transport omitted (defaults to stdio)")
    func decodesMinimalConfig() throws {
        let json = """
        {
          "mcpServers": {
            "simple-mcp": {
              "command": "npx"
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)

        let entry = try #require(config.mcpServers["simple-mcp"])
        #expect(entry.transport == nil)  // Omitted
        #expect(entry.command == "npx")
        #expect(entry.args == nil)
        #expect(entry.cwd == nil)
        #expect(entry.env == nil)
        #expect(entry.disabled == nil)
        #expect(entry.override == nil)
    }

    @Test("Decodes empty mcpServers object")
    func decodesEmptyMcpServers() throws {
        let json = """
        {
          "mcpServers": {}
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)

        #expect(config.mcpServers.isEmpty)
    }

    @Test("Decodes disabled flag")
    func decodesDisabledFlag() throws {
        let json = """
        {
          "mcpServers": {
            "inactive": {
              "command": "python3",
              "disabled": true
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["inactive"])

        #expect(entry.disabled == true)
    }

    @Test("Decodes override flag")
    func decodesOverrideFlag() throws {
        let json = """
        {
          "mcpServers": {
            "priority-mcp": {
              "command": "python3",
              "override": true
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["priority-mcp"])

        #expect(entry.override == true)
    }

    @Test("Decodes env_secret_keys (snake_case in JSON -> camelCase in Swift)")
    func decodesEnvSecretKeys() throws {
        let json = """
        {
          "mcpServers": {
            "with-secrets": {
              "command": "python3",
              "env": {
                "API_TOKEN": "mock-api-token",
                "REGULAR_VAR": "normal"
              },
              "env_secret_keys": ["API_TOKEN"]
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["with-secrets"])

        #expect(entry.envSecretKeys == ["API_TOKEN"])
    }

    @Test("Decodes headers_secret_keys (snake_case in JSON -> camelCase in Swift)")
    func decodesHeadersSecretKeys() throws {
        let json = """
        {
          "mcpServers": {
            "http-secrets": {
              "transport": "streamable-http",
              "url": "https://api.example.com",
              "headers": {
                "Authorization": "Bearer xyz"
              },
              "headers_secret_keys": ["Authorization"]
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["http-secrets"])

        #expect(entry.headersSecretKeys == ["Authorization"])
    }

    // MARK: - Validation Tests

    @Test("Validates stdio entry requires command")
    func validatesStdioRequiresCommand() throws {
        let json = """
        {
          "mcpServers": {
            "no-command": {
              "transport": "stdio",
              "args": ["arg1"]
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let errors = config.validate()

        #expect(errors.count == 1)
        #expect(errors[0].contains("no-command"))
        #expect(errors[0].contains("command"))
    }

    @Test("Validates HTTP entry requires url")
    func validatesHTTPRequiresUrl() throws {
        let json = """
        {
          "mcpServers": {
            "no-url": {
              "transport": "streamable-http"
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let errors = config.validate()

        #expect(errors.count == 1)
        #expect(errors[0].contains("no-url"))
        #expect(errors[0].contains("url"))
    }

    @Test("Validates unknown transport returns warning")
    func validatesUnknownTransport() throws {
        let json = """
        {
          "mcpServers": {
            "bad-transport": {
              "transport": "websocket",
              "command": "python3"
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let errors = config.validate()

        #expect(errors.count == 1)
        #expect(errors[0].contains("unknown transport"))
        #expect(errors[0].contains("websocket"))
    }

    @Test("Accepts empty command with warning (whitespace only)")
    func validatesEmptyCommand() throws {
        let json = """
        {
          "mcpServers": {
            "empty-cmd": {
              "transport": "stdio",
              "command": "   "
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let errors = config.validate()

        #expect(errors.count == 1)
        #expect(errors[0].contains("empty-cmd"))
    }

    // MARK: - File Loading Tests

    @Test("Loads from file on disk")
    func loadsFromFileDisk() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-mcps-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let json = """
        {
          "mcpServers": {
            "test-server": {
              "command": "echo"
            }
          }
        }
        """.data(using: .utf8)!

        try json.write(to: URL(fileURLWithPath: configPath))

        let config = try MCPConfig.load(from: configPath)

        #expect(config.mcpServers.count == 1)
        #expect(config.mcpServers["test-server"] != nil)
    }

    @Test("Creates default empty file when missing")
    func createsDefaultEmptyFile() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("default-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        // Path should not exist yet
        #expect(!FileManager.default.fileExists(atPath: configPath))

        let config = try MCPConfig.loadOrCreateDefault(at: configPath)

        // File should now exist
        #expect(FileManager.default.fileExists(atPath: configPath))
        #expect(config.mcpServers.isEmpty)
    }

    @Test("Loads existing file instead of overwriting")
    func loadsExistingFileNotOverwrite() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("existing-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let json = """
        {
          "mcpServers": {
            "existing-server": {
              "command": "python3"
            }
          }
        }
        """.data(using: .utf8)!

        try json.write(to: URL(fileURLWithPath: configPath))

        let config = try MCPConfig.loadOrCreateDefault(at: configPath)

        #expect(config.mcpServers.count == 1)
        #expect(config.mcpServers["existing-server"] != nil)
    }

    @Test("Handles malformed JSON gracefully")
    func handlesMalformedJSON() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("bad-json-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let badJSON = "{ broken json".data(using: .utf8)!
        try badJSON.write(to: URL(fileURLWithPath: configPath))

        #expect(throws: DecodingError.self) {
            try MCPConfig.load(from: configPath)
        }
    }

    @Test("Missing file throws error")
    func missingFileThrows() throws {
        let nonExistentPath = "/tmp/nonexistent-\(UUID().uuidString).json"

        #expect(throws: Error.self) {
            try MCPConfig.load(from: nonExistentPath)
        }
    }

    // MARK: - Default Path Test

    @Test("defaultPath points to the centralized mcps.json path")
    func defaultPathIsConfigured() {
        let path = MCPConfig.defaultPath
        #expect(path == PathManager.shared.mcpsConfigFile.path)
    }

    // MARK: - Claude Desktop Compatibility Tests

    @Test("Decodes Claude Desktop compatible format")
    func decodesClaudeDesktopFormat() throws {
        // This is the exact format from Claude Desktop
        let json = """
        {
          "mcpServers": {
            "filesystem": {
              "command": "npx",
              "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/user/Documents"]
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["filesystem"])

        // Should work without transport (defaults to stdio)
        #expect(entry.transport == nil)
        #expect(entry.command == "npx")
        #expect(entry.args == ["-y", "@modelcontextprotocol/server-filesystem", "/Users/user/Documents"])
    }

    @Test("Multiple MCPs in single config")
    func multipleEntriesInConfig() throws {
        let json = """
        {
          "mcpServers": {
            "python-server": {
              "command": "python3",
              "args": ["server.py"]
            },
            "node-server": {
              "command": "node",
              "args": ["index.js"]
            },
            "http-server": {
              "transport": "streamable-http",
              "url": "https://example.com"
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)

        #expect(config.mcpServers.count == 3)
        #expect(config.mcpServers.keys.contains("python-server"))
        #expect(config.mcpServers.keys.contains("node-server"))
        #expect(config.mcpServers.keys.contains("http-server"))
    }

    // MARK: - Timeout Tests

    @Test("Decodes timeout field for stdio MCP")
    func decodesTimeoutForStdio() throws {
        let json = """
        {
          "mcpServers": {
            "timeout-stdio": {
              "command": "python3",
              "timeout": 60
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["timeout-stdio"])

        #expect(entry.timeout == 60)
    }

    @Test("Decodes timeout field for HTTP MCP")
    func decodesTimeoutForHTTP() throws {
        let json = """
        {
          "mcpServers": {
            "timeout-http": {
              "transport": "streamable-http",
              "url": "https://api.example.com",
              "timeout": 45
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["timeout-http"])

        #expect(entry.timeout == 45)
    }

    @Test("Decodes omitted timeout as nil (uses default)")
    func decodesOmittedTimeoutAsNil() throws {
        let json = """
        {
          "mcpServers": {
            "default-timeout": {
              "command": "python3"
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["default-timeout"])

        #expect(entry.timeout == nil)
    }

    @Test("Decodes zero timeout")
    func decodesZeroTimeout() throws {
        let json = """
        {
          "mcpServers": {
            "zero-timeout": {
              "command": "python3",
              "timeout": 0
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["zero-timeout"])

        #expect(entry.timeout == 0)
    }

    @Test("Decodes large timeout value")
    func decodesLargeTimeout() throws {
        let json = """
        {
          "mcpServers": {
            "large-timeout": {
              "command": "python3",
              "timeout": 3600
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["large-timeout"])

        #expect(entry.timeout == 3600)
    }

    @Test("Encodes timeout in JSON output")
    func encodesTimeoutInJSON() throws {
        let entry = MCPConfig.ServerEntry(
            transport: "stdio",
            command: "python3",
            args: nil,
            cwd: nil,
            env: nil,
            envSecretKeys: nil,
            url: nil,
            headers: nil,
            headersSecretKeys: nil,
            disabled: nil,
            override: nil,
            timeout: 45,
            healthCheck: nil
        )

        let config = MCPConfig(mcpServers: ["test-server": entry])
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        let data = try encoder.encode(config)
        let jsonString = try #require(String(data: data, encoding: .utf8))

        #expect(jsonString.contains("\"timeout\" : 45"))
    }

    @Test("Timeout in mixed config with multiple MCPs")
    func timeoutInMixedConfig() throws {
        let json = """
        {
          "mcpServers": {
            "server-with-timeout": {
              "command": "python3",
              "timeout": 60
            },
            "server-without-timeout": {
              "command": "node",
              "args": ["server.js"]
            },
            "http-with-timeout": {
              "transport": "streamable-http",
              "url": "https://api.example.com",
              "timeout": 30
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)

        let withTimeout = try #require(config.mcpServers["server-with-timeout"])
        #expect(withTimeout.timeout == 60)

        let withoutTimeout = try #require(config.mcpServers["server-without-timeout"])
        #expect(withoutTimeout.timeout == nil)

        let httpWithTimeout = try #require(config.mcpServers["http-with-timeout"])
        #expect(httpWithTimeout.timeout == 30)
    }

    // MARK: - Health Check Configuration Tests (R25)

    @Test("Decodes health_check configuration")
    func decodesHealthCheckConfig() throws {
        let json = """
        {
          "mcpServers": {
            "with-health-check": {
              "command": "python3",
              "health_check": {
                "enabled": true,
                "interval": 30,
                "timeout": 10,
                "retries": 3
              }
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["with-health-check"])

        let healthCheck = try #require(entry.healthCheck)
        #expect(healthCheck.enabled == true)
        #expect(healthCheck.interval == 30)
        #expect(healthCheck.timeout == 10)
        #expect(healthCheck.retries == 3)
    }

    @Test("Decodes health_check with partial fields")
    func decodesPartialHealthCheck() throws {
        let json = """
        {
          "mcpServers": {
            "partial-health-check": {
              "command": "node",
              "health_check": {
                "enabled": false,
                "interval": 60
              }
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["partial-health-check"])

        let healthCheck = try #require(entry.healthCheck)
        #expect(healthCheck.enabled == false)
        #expect(healthCheck.interval == 60)
        #expect(healthCheck.timeout == nil)
        #expect(healthCheck.retries == nil)
    }

    @Test("Decodes config without health_check field")
    func decodesWithoutHealthCheck() throws {
        let json = """
        {
          "mcpServers": {
            "no-health-check": {
              "command": "python3"
            }
          }
        }
        """.data(using: .utf8)!

        let config = try JSONDecoder().decode(MCPConfig.self, from: json)
        let entry = try #require(config.mcpServers["no-health-check"])

        #expect(entry.healthCheck == nil)
    }

    @Test("Encodes health_check configuration to JSON")
    func encodesHealthCheckConfig() throws {
        let healthCheckConfig = MCPConfig.HealthCheckConfig(
            enabled: true,
            interval: 45,
            timeout: 15,
            retries: 5
        )
        let entry = MCPConfig.ServerEntry(
            transport: "stdio",
            command: "python3",
            args: nil,
            cwd: nil,
            env: nil,
            envSecretKeys: nil,
            url: nil,
            headers: nil,
            headersSecretKeys: nil,
            disabled: nil,
            override: nil,
            timeout: nil,
            healthCheck: healthCheckConfig
        )

        let config = MCPConfig(mcpServers: ["test-hc": entry])
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        let data = try encoder.encode(config)
        let jsonString = try #require(String(data: data, encoding: .utf8))

        #expect(jsonString.contains("\"health_check\""))
        #expect(jsonString.contains("\"enabled\" : true"))
        #expect(jsonString.contains("\"interval\" : 45"))
        #expect(jsonString.contains("\"timeout\" : 15"))
        #expect(jsonString.contains("\"retries\" : 5"))
    }

    @Test("Round-trip encode/decode health_check config")
    func roundTripHealthCheckConfig() throws {
        let original = """
        {
          "mcpServers": {
            "test": {
              "command": "python3",
              "health_check": {
                "enabled": false,
                "interval": 120,
                "timeout": 20,
                "retries": 2
              }
            }
          }
        }
        """

        let data = try #require(original.data(using: .utf8))
        let decoded = try JSONDecoder().decode(MCPConfig.self, from: data)

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let reencoded = try encoder.encode(decoded)

        let redecodedData = try JSONDecoder().decode(MCPConfig.self, from: reencoded)
        let entry = try #require(redecodedData.mcpServers["test"])
        let healthCheck = try #require(entry.healthCheck)

        #expect(healthCheck.enabled == false)
        #expect(healthCheck.interval == 120)
        #expect(healthCheck.timeout == 20)
        #expect(healthCheck.retries == 2)
    }
}
