import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "DependencyChecker")

/// Result of checking a single dependency
struct DependencyCheckResult: Sendable {
    let name: String
    let required: String
    let found: String?
    let satisfied: Bool
    let message: String
}

/// Checks runtime dependencies for MCP servers
@MainActor final class DependencyChecker {

    /// Extra PATH locations for GUI apps
    private let extraPATH = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin"

    /// Check all dependencies for a manifest
    func check(_ manifest: MCPManifest) async -> [DependencyCheckResult] {
        var results: [DependencyCheckResult] = []

        // Check runtime
        if let runtime = manifest.dependencies?.runtime {
            let result = await checkRuntime(runtime)
            results.append(result)
        }

        // Check if command exists
        let commandResult = await checkCommand(manifest.command)
        results.append(commandResult)

        return results
    }

    /// Check runtime dependency (e.g., "python3.10+")
    private func checkRuntime(_ runtime: String) async -> DependencyCheckResult {
        // Parse: "python3.10+" → command="python3", minVersion="3.10"
        let parsed = parseRuntime(runtime)

        // Run command --version on background thread
        let versionOutput = await Task.detached { [extraPATH] in
            Self.runVersionCheck(command: parsed.command, extraPATH: extraPATH)
        }.value

        guard let version = versionOutput else {
            return DependencyCheckResult(
                name: parsed.command,
                required: runtime,
                found: nil,
                satisfied: false,
                message: "\(parsed.command) not found in PATH"
            )
        }

        if let minVersion = parsed.minVersion {
            let satisfied = Self.compareVersions(found: version, minimum: minVersion)
            return DependencyCheckResult(
                name: parsed.command,
                required: runtime,
                found: version,
                satisfied: satisfied,
                message: satisfied ? "\(parsed.command) \(version) ≥ \(minVersion)" : "\(parsed.command) \(version) < \(minVersion) required"
            )
        }

        return DependencyCheckResult(
            name: parsed.command,
            required: runtime,
            found: version,
            satisfied: true,
            message: "\(parsed.command) \(version) found"
        )
    }

    /// Check if a command is available in PATH
    private func checkCommand(_ command: String) async -> DependencyCheckResult {
        let found = await Task.detached { [extraPATH] in
            Self.commandExists(command: command, extraPATH: extraPATH)
        }.value

        return DependencyCheckResult(
            name: command,
            required: command,
            found: found ? command : nil,
            satisfied: found,
            message: found ? "\(command) found" : "\(command) not found in PATH"
        )
    }

    // MARK: - Parsing

    struct ParsedRuntime {
        let command: String
        let minVersion: String?
    }

    /// Parse runtime string like "python3.10+" or "node18+"
    ///
    /// Strategy: find the last `major.minor[.patch]` version pattern in the string.
    /// Everything before it is the command name. This correctly handles names
    /// like "python3" where a single digit is part of the command, not the version.
    ///
    /// Examples:
    ///   "python3.10+"  → command="python3", minVersion="3.10"
    ///   "python3.11.5" → command="python3", minVersion="3.11.5"
    ///   "node18+"      → command="node", minVersion="18"
    ///   "ruby"         → command="ruby", minVersion=nil
    func parseRuntime(_ runtime: String) -> ParsedRuntime {
        // Strip trailing "+"
        var cleaned = runtime
        let hasMin = cleaned.hasSuffix("+")
        if hasMin { cleaned.removeLast() }

        // Try to find a "major.minor[.patch]" version at the end
        // Pattern: digits followed by dot and more digits, optionally repeated
        let versionPattern = #"(\d+\.\d+(?:\.\d+)?)$"#
        if let regex = try? NSRegularExpression(pattern: versionPattern),
           let match = regex.firstMatch(in: cleaned, range: NSRange(cleaned.startIndex..., in: cleaned)),
           let versionRange = Range(match.range(at: 1), in: cleaned) {
            let version = String(cleaned[versionRange])
            let command = String(cleaned[cleaned.startIndex..<versionRange.lowerBound])
            return ParsedRuntime(command: command, minVersion: hasMin ? version : version)
        }

        // Fallback: try a bare major version at the end (e.g., "node18")
        let bareVersionPattern = #"^([a-zA-Z][a-zA-Z0-9_-]*)(\d+)$"#
        if let regex = try? NSRegularExpression(pattern: bareVersionPattern),
           let match = regex.firstMatch(in: cleaned, range: NSRange(cleaned.startIndex..., in: cleaned)),
           let cmdRange = Range(match.range(at: 1), in: cleaned),
           let verRange = Range(match.range(at: 2), in: cleaned) {
            let command = String(cleaned[cmdRange])
            let version = String(cleaned[verRange])
            return ParsedRuntime(command: command, minVersion: hasMin ? version : version)
        }

        // No version found — the whole string is the command
        return ParsedRuntime(command: cleaned, minVersion: nil)
    }

    // MARK: - Static Helpers (run off main actor)

    /// Runs `command --version` and extracts version string
    nonisolated private static func runVersionCheck(command: String, extraPATH: String) -> String? {
        let process = Foundation.Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [command, "--version"]

        var env = ProcessInfo.processInfo.environment
        let currentPATH = env["PATH"] ?? "/usr/bin:/bin"
        env["PATH"] = "\(extraPATH):\(currentPATH)"
        process.environment = env

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe  // some tools output version to stderr

        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""
            return extractVersion(from: output)
        } catch {
            return nil
        }
    }

    /// Extracts version number from version command output
    nonisolated static func extractVersion(from output: String) -> String? {
        // Match patterns like "3.10.2", "18.19.0", "Python 3.11.5"
        let pattern = #"(\d+\.\d+(?:\.\d+)?)"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: output, range: NSRange(output.startIndex..., in: output)),
              let range = Range(match.range(at: 1), in: output) else {
            return nil
        }
        return String(output[range])
    }

    /// Checks if a command exists using `which`
    nonisolated private static func commandExists(command: String, extraPATH: String) -> Bool {
        let process = Foundation.Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["which", command]

        var env = ProcessInfo.processInfo.environment
        let currentPATH = env["PATH"] ?? "/usr/bin:/bin"
        env["PATH"] = "\(extraPATH):\(currentPATH)"
        process.environment = env

        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice

        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus == 0
        } catch {
            return false
        }
    }

    /// Compare version strings (simple numeric comparison)
    nonisolated static func compareVersions(found: String, minimum: String) -> Bool {
        let foundParts = found.split(separator: ".").compactMap { Int($0) }
        let minParts = minimum.split(separator: ".").compactMap { Int($0) }

        for i in 0..<max(foundParts.count, minParts.count) {
            let f = i < foundParts.count ? foundParts[i] : 0
            let m = i < minParts.count ? minParts[i] : 0
            if f > m { return true }
            if f < m { return false }
        }
        return true  // equal
    }
}
