import Foundation

/// Represents the Claude config file format (mcps.json)
struct MCPConfig: Codable, Sendable {
    let mcpServers: [String: ServerEntry]

    /// Default path for the config file managed by PathManager.
    static var defaultPath: String {
        PathManager.shared.mcpsConfigFile.path
    }

    struct HealthCheckConfig: Codable, Sendable, Equatable {
        let enabled: Bool?
        let interval: Int?
        let timeout: Int?
        let retries: Int?
    }

    struct MigrationLogEntry: Codable, Sendable, Equatable {
        let name: String
        let transport: String
        let command: String?
        let args: [String]
        let cwd: String?
        let env: [String: String]?
        let envSecretKeys: [String]?
        let migratedFrom: String
        let source: String
        let validatedAt: Date

        enum CodingKeys: String, CodingKey {
            case name
            case transport
            case command
            case args
            case cwd
            case env
            case envSecretKeys = "env_secret_keys"
            case migratedFrom = "migrated_from"
            case source
            case validatedAt = "validated_at"
        }
    }

    struct MigrationLog: Codable, Sendable, Equatable {
        let entries: [String: MigrationLogEntry]

        static func loadOrCreateDefault(at path: String) throws -> MigrationLog {
            let url = URL(fileURLWithPath: path)
            let parentDir = url.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: parentDir, withIntermediateDirectories: true)

            if FileManager.default.fileExists(atPath: path) {
                let data = try Data(contentsOf: url)
                let decoder = JSONDecoder()
                decoder.dateDecodingStrategy = .iso8601
                return try decoder.decode(MigrationLog.self, from: data)
            }

            let log = MigrationLog(entries: [:])
            try log.save(to: path)
            return log
        }

        func save(to path: String) throws {
            let url = URL(fileURLWithPath: path)
            let parentDir = url.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: parentDir, withIntermediateDirectories: true)

            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(self)
            try data.write(to: url, options: .atomic)
        }
    }

    /// Server entry in mcps.json
    struct ServerEntry: Codable, Sendable {
        let transport: String?
        let command: String?
        let args: [String]?
        let cwd: String?
        let env: [String: String]?
        let url: String?
        let headers: [String: String]?
        let disabled: Bool?
        let override: Bool?
        let timeout: Int?
        let envSecretKeys: [String]?
        let headersSecretKeys: [String]?
        let healthCheck: HealthCheckConfig?
        let migratedFrom: String?

        init(
            transport: String?,
            command: String?,
            args: [String]?,
            cwd: String?,
            env: [String: String]?,
            envSecretKeys: [String]?,
            url: String?,
            headers: [String: String]?,
            headersSecretKeys: [String]?,
            disabled: Bool?,
            override: Bool?,
            timeout: Int?,
            healthCheck: HealthCheckConfig?,
            migratedFrom: String? = nil
        ) {
            self.transport = transport
            self.command = command
            self.args = args
            self.cwd = cwd
            self.env = env
            self.envSecretKeys = envSecretKeys
            self.url = url
            self.headers = headers
            self.headersSecretKeys = headersSecretKeys
            self.disabled = disabled
            self.override = override
            self.timeout = timeout
            self.healthCheck = healthCheck
            self.migratedFrom = migratedFrom
        }

        init(manifest: MCPManifest, directory: URL) {
            self.init(
                transport: manifest.transport,
                command: manifest.command,
                args: manifest.args,
                cwd: directory.path,
                env: manifest.env,
                envSecretKeys: manifest.env_secret_keys,
                url: nil,
                headers: nil,
                headersSecretKeys: nil,
                disabled: nil,
                override: nil,
                timeout: nil,
                healthCheck: nil,
                migratedFrom: directory.path
            )
        }

        enum CodingKeys: String, CodingKey {
            case transport
            case command
            case args
            case cwd
            case env
            case url
            case headers
            case disabled
            case override
            case timeout
            case env_secret_keys = "env_secret_keys"
            case headers_secret_keys = "headers_secret_keys"
            case health_check = "health_check"
            case migrated_from = "migrated_from"
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            transport = try container.decodeIfPresent(String.self, forKey: .transport)
            command = try container.decodeIfPresent(String.self, forKey: .command)
            args = try container.decodeIfPresent([String].self, forKey: .args)
            cwd = try container.decodeIfPresent(String.self, forKey: .cwd)
            env = try container.decodeIfPresent([String: String].self, forKey: .env)
            url = try container.decodeIfPresent(String.self, forKey: .url)
            headers = try container.decodeIfPresent([String: String].self, forKey: .headers)
            disabled = try container.decodeIfPresent(Bool.self, forKey: .disabled)
            override = try container.decodeIfPresent(Bool.self, forKey: .override)
            timeout = try container.decodeIfPresent(Int.self, forKey: .timeout)
            envSecretKeys = try container.decodeIfPresent([String].self, forKey: .env_secret_keys)
            headersSecretKeys = try container.decodeIfPresent([String].self, forKey: .headers_secret_keys)
            healthCheck = try container.decodeIfPresent(HealthCheckConfig.self, forKey: .health_check)
            migratedFrom = try container.decodeIfPresent(String.self, forKey: .migrated_from)
        }

        func encode(to encoder: Encoder) throws {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encodeIfPresent(transport, forKey: .transport)
            try container.encodeIfPresent(command, forKey: .command)
            try container.encodeIfPresent(args, forKey: .args)
            try container.encodeIfPresent(cwd, forKey: .cwd)
            try container.encodeIfPresent(env, forKey: .env)
            try container.encodeIfPresent(url, forKey: .url)
            try container.encodeIfPresent(headers, forKey: .headers)
            try container.encodeIfPresent(disabled, forKey: .disabled)
            try container.encodeIfPresent(override, forKey: .override)
            try container.encodeIfPresent(timeout, forKey: .timeout)
            try container.encodeIfPresent(envSecretKeys, forKey: .env_secret_keys)
            try container.encodeIfPresent(headersSecretKeys, forKey: .headers_secret_keys)
            try container.encodeIfPresent(healthCheck, forKey: .health_check)
            try container.encodeIfPresent(migratedFrom, forKey: .migrated_from)
        }

        func migrationLogEntry(
            named name: String,
            source: MCPSource = .config,
            validatedAt: Date = Date()
        ) -> MigrationLogEntry? {
            guard let migratedFrom else { return nil }

            return MigrationLogEntry(
                name: name,
                transport: transport ?? "stdio",
                command: command,
                args: args ?? [],
                cwd: cwd,
                env: env,
                envSecretKeys: envSecretKeys,
                migratedFrom: migratedFrom,
                source: source.rawValue,
                validatedAt: validatedAt
            )
        }
    }

    /// Load config from file
    static func load(from path: String) throws -> MCPConfig {
        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: path) else {
            throw ConfigError.fileNotFound(path)
        }

        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let config = try JSONDecoder().decode(MCPConfig.self, from: data)
        return config
    }

    /// Creates a default empty config file if it doesn't exist.
    static func loadOrCreateDefault(at path: String) throws -> MCPConfig {
        let url = URL(fileURLWithPath: path)
        let parentDir = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: parentDir, withIntermediateDirectories: true)

        if FileManager.default.fileExists(atPath: path) {
            return try load(from: path)
        }

        let defaultConfig = MCPConfig(mcpServers: [:])
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(defaultConfig)
        try data.write(to: url)
        return defaultConfig
    }

    /// Save config to file
    func save(to path: String) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(self)
        try data.write(to: URL(fileURLWithPath: path))
    }

    /// Validate config structure
    func validate() -> [String] {
        var errors: [String] = []

        for (name, entry) in mcpServers {
            let transport = entry.transport ?? "stdio"

            // Validate stdio servers
            if transport == "stdio" {
                if entry.command?.trimmingCharacters(in: .whitespaces).isEmpty ?? true {
                    errors.append("\(name): stdio servers require 'command'")
                }
            }
            // Validate HTTP servers
            else if transport.contains("http") || transport == "sse" {
                if entry.url?.isEmpty ?? true {
                    errors.append("\(name): HTTP servers require 'url'")
                }
            }
            // Warn on unknown transports
            else {
                errors.append("\(name): unknown transport '\(transport)'")
            }
        }

        return errors
    }

    /// Encode to JSON string, preserving formatting
    func toJSON() throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(self)
        return String(data: data, encoding: .utf8) ?? ""
    }
}

enum ConfigError: Error, LocalizedError {
    case fileNotFound(String)
    case invalidJSON(String)
    case saveFailed(String)

    var errorDescription: String? {
        switch self {
        case .fileNotFound(let path):
            return L10n.format("error.config.fileNotFound", path)
        case .invalidJSON(let message):
            return L10n.format("error.config.invalidJson", message)
        case .saveFailed(let message):
            return L10n.format("error.config.saveFailed", message)
        }
    }
}
