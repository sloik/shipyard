import Testing
import Foundation
@testable import Shipyard

@Suite("MCPManifest")
struct ManifestTests {

    @Test("Decodes valid full manifest JSON")
    func decodesValidFullManifest() throws {
        let json = """
        {
            "name": "test-server",
            "version": "1.0.0",
            "description": "A test server",
            "transport": "stdio",
            "command": "python3",
            "args": ["server.py"],
            "env": {"PYTHONUNBUFFERED": "1"},
            "env_secret_keys": ["API_TOKEN"],
            "dependencies": {
                "runtime": "python3.10+",
                "packages": ["fastmcp>=0.1.0"]
            },
            "health_check": {
                "tool": "run_command",
                "args": {"command": "echo ok"},
                "expect": {"status": "ok"}
            },
            "logging": {
                "capability": true,
                "levels": ["debug", "info"]
            },
            "install": {
                "script": "install.sh",
                "test_script": "test_server.py"
            }
        }
        """.data(using: .utf8)!

        let manifest = try JSONDecoder().decode(MCPManifest.self, from: json)
        #expect(manifest.name == "test-server")
        #expect(manifest.version == "1.0.0")
        #expect(manifest.description == "A test server")
        #expect(manifest.transport == "stdio")
        #expect(manifest.command == "python3")
        #expect(manifest.args == ["server.py"])
        #expect(manifest.env?["PYTHONUNBUFFERED"] == "1")
        #expect(manifest.env_secret_keys == ["API_TOKEN"])
        #expect(manifest.dependencies?.runtime == "python3.10+")
        #expect(manifest.dependencies?.packages == ["fastmcp>=0.1.0"])
        #expect(manifest.health_check?.tool == "run_command")
        #expect(manifest.logging?.capability == true)
        #expect(manifest.install?.script == "install.sh")
    }

    @Test("Decodes minimal manifest (required fields only)")
    func decodesMinimalManifest() throws {
        let json = """
        {
            "name": "minimal",
            "version": "0.1.0",
            "description": "Minimal server",
            "transport": "stdio",
            "command": "node",
            "args": []
        }
        """.data(using: .utf8)!

        let manifest = try JSONDecoder().decode(MCPManifest.self, from: json)
        #expect(manifest.name == "minimal")
        #expect(manifest.env == nil)
        #expect(manifest.env_secret_keys == nil)
        #expect(manifest.dependencies == nil)
        #expect(manifest.health_check == nil)
        #expect(manifest.logging == nil)
        #expect(manifest.install == nil)
    }

    @Test("Throws on missing required field 'name'")
    func throwsOnMissingName() {
        let json = """
        {
            "version": "1.0.0",
            "description": "No name",
            "transport": "stdio",
            "command": "python3",
            "args": []
        }
        """.data(using: .utf8)!

        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(MCPManifest.self, from: json)
        }
    }

    @Test("Throws on missing required field 'command'")
    func throwsOnMissingCommand() {
        let json = """
        {
            "name": "test",
            "version": "1.0.0",
            "description": "No command",
            "transport": "stdio",
            "args": []
        }
        """.data(using: .utf8)!

        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(MCPManifest.self, from: json)
        }
    }

    @Test("Decodes empty args array")
    func decodesEmptyArgs() throws {
        let json = """
        {
            "name": "test",
            "version": "1.0.0",
            "description": "Empty args",
            "transport": "stdio",
            "command": "python3",
            "args": []
        }
        """.data(using: .utf8)!

        let manifest = try JSONDecoder().decode(MCPManifest.self, from: json)
        #expect(manifest.args.isEmpty)
    }
}
