import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ClaudeConfigImporter")

/// Result of importing from Claude Desktop config
struct ImportResult: Sendable {
    let imported: Int
    let skipped: Int
    let errors: [String]

    var message: String {
        if errors.isEmpty {
            return "Imported \(imported) MCP\(imported == 1 ? "" : "s"), skipped \(skipped)"
        } else {
            let errorMsg = errors.prefix(3).joined(separator: "; ")
            let more = errors.count > 3 ? " (\(errors.count - 3) more)" : ""
            return "Imported \(imported), skipped \(skipped). Errors: \(errorMsg)\(more)"
        }
    }
}

/// Imports MCP entries from Claude Desktop config into Shipyard's mcps.json
final class ClaudeConfigImporter: Sendable {
    /// Claude Desktop config path
    static let defaultClaudeConfigPath = "~/Library/Application Support/Claude/claude_desktop_config.json"

    /// Overridable source and destination paths (for testing)
    private let claudeConfigPath: String
    private let shipyardConfigPath: String?

    init(claudeConfigPath: String = ClaudeConfigImporter.defaultClaudeConfigPath,
         shipyardConfigPath: String? = nil) {
        self.claudeConfigPath = claudeConfigPath
        self.shipyardConfigPath = shipyardConfigPath
    }

    /// Import MCPs from Claude Desktop config and merge into mcps.json
    func importFromClaudeConfig() async -> ImportResult {
        let expandedPath = (claudeConfigPath as NSString).expandingTildeInPath
        let configURL = URL(fileURLWithPath: expandedPath)

        // Check if file exists
        guard FileManager.default.fileExists(atPath: expandedPath) else {
            log.warning("Claude Desktop config not found at: \(expandedPath)")
            return ImportResult(imported: 0, skipped: 0, errors: ["Claude Desktop config not found at \(claudeConfigPath)"])
        }

        // Read and parse Claude config
        let claudeConfig: [String: Any]
        do {
            let data = try Data(contentsOf: configURL)
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                let error = "Claude config is not a valid JSON object"
                log.error("\(error)")
                return ImportResult(imported: 0, skipped: 0, errors: [error])
            }
            claudeConfig = json
        } catch {
            let errorMsg = "Failed to read Claude Desktop config: \(error.localizedDescription)"
            log.error("\(errorMsg)")
            return ImportResult(imported: 0, skipped: 0, errors: [errorMsg])
        }

        // Extract mcpServers
        guard let mcpServers = claudeConfig["mcpServers"] as? [String: Any] else {
            let error = "Claude config has no 'mcpServers' section"
            log.info("\(error)")
            return ImportResult(imported: 0, skipped: 0, errors: [error])
        }

        // Convert entries to MCPConfig.ServerEntry format
        var convertedServers: [String: MCPConfig.ServerEntry] = [:]
        var skipped = 0
        var errors: [String] = []

        for (name, entry) in mcpServers {
            guard let entryDict = entry as? [String: Any] else {
                let msg = "MCP '\(name)': entry is not a valid object"
                errors.append(msg)
                skipped += 1
                continue
            }

            let command = entryDict["command"] as? String
            let args = entryDict["args"] as? [String]
            let env = entryDict["env"] as? [String: String]

            // Claude Desktop config uses stdio by default
            // All entries are stdio transport (no HTTP support in Claude Desktop config)
            let serverEntry = MCPConfig.ServerEntry(
                transport: "stdio",
                command: command,
                args: args,
                cwd: nil,  // Claude Desktop config doesn't include cwd
                env: env,
                envSecretKeys: nil,
                url: nil,
                headers: nil,
                headersSecretKeys: nil,
                disabled: nil,  // Default to enabled
                override: nil,  // Don't override by default
                timeout: nil,   // Use default timeout
                healthCheck: nil  // No health check config in Claude Desktop import
            )

            convertedServers[name] = serverEntry
            log.debug("Converted Claude config entry: \(name)")
        }

        // Load existing mcps.json or create default
        let mcpsJsonPath: URL
        if let customPath = shipyardConfigPath {
            mcpsJsonPath = URL(fileURLWithPath: customPath)
        } else {
            mcpsJsonPath = PathManager.shared.mcpsConfigFile
        }

        var existingConfig: MCPConfig
        if FileManager.default.fileExists(atPath: mcpsJsonPath.path) {
            do {
                let data = try Data(contentsOf: mcpsJsonPath)
                existingConfig = try JSONDecoder().decode(MCPConfig.self, from: data)
            } catch {
                let errorMsg = "Failed to read existing mcps.json: \(error.localizedDescription)"
                log.error("\(errorMsg)")
                return ImportResult(imported: 0, skipped: 0, errors: [errorMsg])
            }
        } else {
            existingConfig = MCPConfig(mcpServers: [:])
        }

        // Merge converted entries into existing config
        var mergedServers = existingConfig.mcpServers
        var imported = 0

        for (name, entry) in convertedServers {
            if mergedServers[name] != nil {
                // Skip if entry already exists
                skipped += 1
                log.info("Skipped existing entry: \(name)")
            } else {
                mergedServers[name] = entry
                imported += 1
                log.info("Added imported entry: \(name)")
            }
        }

        // Write merged config back to mcps.json
        let mergedConfig = MCPConfig(mcpServers: mergedServers)
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(mergedConfig)

            // Ensure directory exists
            let directory = mcpsJsonPath.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

            try data.write(to: mcpsJsonPath)
            log.info("Updated mcps.json with \(imported) imported entries")
        } catch {
            let errorMsg = "Failed to write mcps.json: \(error.localizedDescription)"
            log.error("\(errorMsg)")
            return ImportResult(imported: imported, skipped: skipped, errors: [errorMsg])
        }

        return ImportResult(imported: imported, skipped: skipped, errors: errors)
    }
}
