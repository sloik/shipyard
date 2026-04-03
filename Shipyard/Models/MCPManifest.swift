import Foundation

/// Represents the MCP manifest.json schema for server configuration.
struct MCPManifest: Codable, Sendable {
    let name: String
    let version: String
    let description: String
    let transport: String
    let command: String
    let args: [String]
    let env: [String: String]?
    let env_secret_keys: [String]?
    let dependencies: Dependencies?
    let health_check: HealthCheck?
    let logging: Logging?
    let install: Install?

    /// Root directory where manifest.json was loaded from. Set after loading.
    private(set) var rootDirectory: URL?

    // MARK: - Nested Types

    struct Dependencies: Codable, Sendable {
        let runtime: String?
        let packages: [String]?
    }

    struct HealthCheck: Codable, Sendable {
        let tool: String
        let args: [String: String]?
        let expect: [String: String]?
    }

    struct Logging: Codable, Sendable {
        let capability: Bool?
        let levels: [String]?
    }

    struct Install: Codable, Sendable {
        let script: String?
        let test_script: String?
    }

    // MARK: - Static Methods

    /// Loads manifest.json from the given directory.
    /// Sets rootDirectory property on the loaded manifest.
    static func load(from directory: URL) throws -> MCPManifest {
        let manifestURL = directory.appendingPathComponent("manifest.json")
        let data = try Data(contentsOf: manifestURL)
        var manifest = try JSONDecoder().decode(MCPManifest.self, from: data)
        manifest.rootDirectory = directory
        return manifest
    }

    // MARK: - Codable Customization

    enum CodingKeys: String, CodingKey {
        case name
        case version
        case description
        case transport
        case command
        case args
        case env
        case env_secret_keys
        case dependencies
        case health_check
        case logging
        case install
    }

    mutating func setRootDirectory(_ url: URL) {
        self.rootDirectory = url
    }
}
