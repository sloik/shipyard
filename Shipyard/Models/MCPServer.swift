import Foundation

// MARK: - Availability: This app targets macOS 13.0+

/// Snapshot of process resource usage
struct ProcessStats: Sendable {
    let pid: Int32
    let cpuPercent: Double     // 0.0 - 100.0+
    let memoryMB: Double       // Resident memory in MB
    let timestamp: Date
}

/// Source of a log entry
enum LogSource: String, Sendable, Codable {
    case stderr     // Captured from process stderr
    case mcp        // MCP protocol notifications/message
    case manager    // Shipyard internal events (start/stop/health)
}

/// Log entry for server stderr/stdout capture
struct LogEntry: Identifiable, Sendable {
    let id: UUID = UUID()
    let timestamp: Date
    let message: String
    let level: LogLevel
    let source: LogSource

    init(timestamp: Date, message: String, level: LogLevel = .info, source: LogSource = .stderr) {
        self.timestamp = timestamp
        self.message = message
        self.level = level
        self.source = source
    }
}

/// Log severity levels
enum LogLevel: String, Sendable, Codable {
    case debug
    case info
    case warning
    case error
}

/// Source of an MCP server (manifest or config)
enum MCPSource: String, Sendable, Codable {
    case manifest
    case config
    case synthetic  // Added for BUG-012 support
}

/// Transport type for MCP server
enum MCPTransport: String, Sendable, Codable {
    case stdio = "stdio"
    case streamableHTTP = "streamable-http"
    case sse = "sse"
}

/// Server runtime state
enum ServerState: Sendable, Equatable {
    case idle
    case starting
    case running
    case stopping
    case error(String)

    var isRunning: Bool {
        if case .running = self {
            return true
        }
        return false
    }
}

/// Health status of a server
enum HealthStatus: Sendable, Equatable {
    case healthy
    case unhealthy(String)
    case unknown
}

/// Represents a running or stopped MCP server instance
@Observable @MainActor final class MCPServer: Identifiable, Hashable {
    nonisolated let id: UUID = UUID()
    nonisolated let manifest: MCPManifest
    nonisolated let source: MCPSource
    nonisolated let transport: MCPTransport

    // State and buffer properties
    var state: ServerState = .idle
    var stderrBuffer: [LogEntry] = []
    var startTime: Date?
    var disabled: Bool = false

    // Health and restart properties (Phase 3)
    var healthStatus: HealthStatus = .unknown
    var lastHealthCheck: Date?
    var autoRestartEnabled: Bool = false
    var restartCount: Int = 0
    var lastRestartAttempt: Date?

    // Process resource monitoring (Phase 4.3)
    var processStats: ProcessStats?

    // Dependency check results (Phase 4.4)
    var dependencyResults: [DependencyCheckResult] = []
    var dependenciesChecked: Bool = false

    // Auto-discovery (Spec 004) — orphaned servers and config changes
    var isOrphaned: Bool = false  // Manifest was deleted from disk while running
    var configNeedsRestart: Bool = false  // Manifest changed while running; restart needed to apply
    var isPendingConfigRemoval: Bool = false  // Removed from mcps.json while still running; keep until stopped

    // Config-sourced server properties (BUG-012)
    var configCwd: String?
    var configHTTPEndpoint: String?
    var configTimeout: Int?
    var configEnvSecretKeys: [String]?
    var configHeaderSecretKeys: [String]?
    var configHeaders: [String: String]?
    var migratedFrom: String?

    private let maxBufferSize = 1000

    init(manifest: MCPManifest, source: MCPSource = .manifest, transport: MCPTransport = .stdio) {
        self.manifest = manifest
        self.source = source
        self.transport = transport
    }

    // MARK: - Computed Properties

    var isHTTP: Bool {
        transport == .streamableHTTP || transport == .sse
    }

    var isBuiltin: Bool {
        manifest.version == "builtin"
    }

    var isLegacyMigrated: Bool {
        migratedFrom != nil
    }

    // MARK: - Hashable Conformance

    nonisolated func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }

    nonisolated static func == (lhs: MCPServer, rhs: MCPServer) -> Bool {
        lhs.id == rhs.id
    }

    // MARK: - Log Management

    /// Append a log entry, maintaining max buffer size
    func appendLog(_ entry: LogEntry) {
        stderrBuffer.append(entry)
        if stderrBuffer.count > maxBufferSize {
            stderrBuffer.removeFirst(stderrBuffer.count - maxBufferSize)
        }
    }

    /// Clear all logs
    func clearLogs() {
        stderrBuffer.removeAll()
    }

}
