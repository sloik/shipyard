import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ConfigGenerator")

/// Generates `claude_desktop_config.json` entries from registered MCP server manifests.
///
/// Produces the `mcpServers` block that goes into Claude Desktop's config file,
/// with secrets resolved from Keychain (not stored in cleartext in config).
@MainActor final class ConfigGenerator {

    private let keychainManager: KeychainManager

    init(keychainManager: KeychainManager) {
        self.keychainManager = keychainManager
    }

    // MARK: - Config Targets

    /// Supported config file targets
    enum ConfigTarget: String, CaseIterable, Identifiable, Sendable {
        case claudeDesktop = "Claude Desktop"
        case claudeCode = "Claude Code"

        var id: String { rawValue }

        var configPath: String {
            switch self {
            case .claudeDesktop:
                return "~/Library/Application Support/Claude/claude_desktop_config.json"
            case .claudeCode:
                return "~/.claude/settings.json"
            }
        }

        var configPathExpanded: String {
            NSString(string: configPath).expandingTildeInPath
        }
    }

    // MARK: - Generation

    /// Generates the mcpServers config block for all registered servers.
    /// - Parameters:
    ///   - servers: Registered MCP servers
    ///   - target: Config target (Claude Desktop or Claude Code)
    ///   - includeSecrets: Whether to include secret values from Keychain
    /// - Returns: JSON string of the mcpServers block
    func generate(
        servers: [MCPServer],
        target: ConfigTarget = .claudeDesktop,
        includeSecrets: Bool = false
    ) -> String {
        var mcpServers: [String: Any] = [:]

        for server in servers {
            let manifest = server.manifest
            guard let rootDir = manifest.rootDirectory else { continue }

            var entry: [String: Any] = [
                "command": resolveCommand(manifest.command, rootDir: rootDir),
                "args": resolveArgs(manifest.args, rootDir: rootDir),
            ]

            // Build environment
            var env: [String: String] = manifest.env ?? [:]

            if includeSecrets {
                let secrets = keychainManager.resolveSecrets(for: manifest)
                env.merge(secrets) { _, new in new }
            } else {
                // Add placeholder comments for secrets
                if let secretKeys = manifest.env_secret_keys {
                    for key in secretKeys {
                        env[key] = "<stored in Keychain>"
                    }
                }
            }

            if !env.isEmpty {
                entry["env"] = env
            }

            mcpServers[manifest.name] = entry
        }

        // Auto-register Shipyard MCP itself
        mcpServers["shipyard-mcp"] = [
            "command": "/opt/homebrew/bin/python3",
            "args": [PathManager.shared.shipyardMCPScript.path]
        ]

        let wrapper: [String: Any] = ["mcpServers": mcpServers]

        guard let jsonData = try? JSONSerialization.data(
            withJSONObject: wrapper,
            options: [.prettyPrinted, .sortedKeys]
        ) else {
            return "{}"
        }

        return String(data: jsonData, encoding: .utf8) ?? "{}"
    }

    /// Reads the current Claude Desktop config and extracts existing mcpServers block.
    func readCurrentConfig(target: ConfigTarget) -> String? {
        let path = target.configPathExpanded
        guard let data = FileManager.default.contents(atPath: path),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let mcpServers = json["mcpServers"],
              let mcpData = try? JSONSerialization.data(
                withJSONObject: ["mcpServers": mcpServers],
                options: [.prettyPrinted, .sortedKeys]
              ) else { return nil }

        return String(data: mcpData, encoding: .utf8)
    }

    /// Generates a diff between current config and what Shipyard would generate.
    /// Returns nil if configs match, otherwise returns a human-readable diff.
    func diffConfig(
        servers: [MCPServer],
        target: ConfigTarget
    ) -> ConfigDiff? {
        let generated = generate(servers: servers, target: target, includeSecrets: false)
        guard let current = readCurrentConfig(target: target) else {
            return ConfigDiff(
                hasChanges: true,
                summary: "No existing config found at \(target.configPath)",
                current: "{}",
                generated: generated
            )
        }

        if current == generated {
            return nil  // no changes
        }

        return ConfigDiff(
            hasChanges: true,
            summary: "Config differs from generated version",
            current: current,
            generated: generated
        )
    }

    // MARK: - Setup Instructions

    /// Generates step-by-step setup instructions for a config target.
    func instructions(for target: ConfigTarget, servers: [MCPServer]) -> [SetupStep] {
        var steps: [SetupStep] = []

        switch target {
        case .claudeDesktop:
            steps.append(SetupStep(
                number: 1,
                title: "Open config file",
                detail: "Open Claude Desktop → Settings → Developer → Edit Config\nOr edit directly:",
                code: "open \"\(target.configPath)\""
            ))
            steps.append(SetupStep(
                number: 2,
                title: "Paste mcpServers block",
                detail: "Replace or merge the mcpServers section with the generated config above."
            ))

            // Check for secrets that need manual env setup
            let serversWithSecrets = servers.filter {
                !($0.manifest.env_secret_keys ?? []).isEmpty
            }
            if !serversWithSecrets.isEmpty {
                let secretList = serversWithSecrets.map { server in
                    let keys = server.manifest.env_secret_keys ?? []
                    return "  • \(server.manifest.name): \(keys.joined(separator: ", "))"
                }.joined(separator: "\n")

                steps.append(SetupStep(
                    number: 3,
                    title: "Configure secrets",
                    detail: "The following servers have secrets stored in Keychain:\n\(secretList)\n\nFor Claude Desktop, add the actual values to the env block (Claude Desktop can't read Keychain). Use Shipyard's 'Copy with secrets' to get the actual values."
                ))
            }

            steps.append(SetupStep(
                number: steps.count + 1,
                title: "Restart Claude Desktop",
                detail: "Quit and reopen Claude Desktop to pick up the new config.",
                code: "killall \"Claude\" && open -a \"Claude\""
            ))

        case .claudeCode:
            steps.append(SetupStep(
                number: 1,
                title: "Open settings",
                detail: "Run in your terminal:",
                code: "claude config edit"
            ))
            steps.append(SetupStep(
                number: 2,
                title: "Add MCP servers",
                detail: "Add each server to the mcpServers section of your settings file."
            ))
            steps.append(SetupStep(
                number: steps.count + 1,
                title: "Restart Claude Code",
                detail: "Restart your Claude Code session to pick up the changes.",
                code: "claude --resume"
            ))
        }

        return steps
    }

    // MARK: - Private Helpers

    /// Resolves the command to an absolute path if needed
    private func resolveCommand(_ command: String, rootDir: URL) -> String {
        // For config files, use the full path so Claude Desktop can find the executable
        if command.contains("/") { return command }

        // Common commands — resolve to likely locations
        switch command {
        case "python3":
            // Check homebrew first
            let homebrewPath = "/opt/homebrew/bin/python3"
            if FileManager.default.fileExists(atPath: homebrewPath) {
                return homebrewPath
            }
            return "/usr/bin/python3"
        case "node":
            let homebrewPath = "/opt/homebrew/bin/node"
            if FileManager.default.fileExists(atPath: homebrewPath) {
                return homebrewPath
            }
            return "/usr/local/bin/node"
        default:
            return command
        }
    }

    /// Resolves relative args to absolute paths based on rootDir
    func resolveArgs(_ args: [String], rootDir: URL) -> [String] {
        args.map { arg in
            // If it looks like a relative file path, make it absolute
            if arg.hasSuffix(".py") || arg.hasSuffix(".js") || arg.hasSuffix(".sh") {
                return rootDir.appendingPathComponent(arg).path
            }
            return arg
        }
    }
}

// MARK: - Supporting Types

struct ConfigDiff: Sendable {
    let hasChanges: Bool
    let summary: String
    let current: String
    let generated: String
}

struct SetupStep: Identifiable, Sendable {
    let id = UUID()
    let number: Int
    let title: String
    let detail: String
    let code: String?
    
    init(number: Int, title: String, detail: String, code: String? = nil) {
        self.number = number
        self.title = title
        self.detail = detail
        self.code = code
    }
}
