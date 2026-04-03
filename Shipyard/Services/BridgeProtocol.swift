import Foundation

/// Transport-agnostic interface for MCP communication.
/// Both MCPBridge (stdio) and HTTPBridge conform to this protocol.
/// NOTE: Conformers may be MainActor-isolated (stdio) or nonisolated (HTTP).
@MainActor
protocol BridgeProtocol {
    var mcpName: String { get }

    /// Initialize the MCP connection (stdio: send initialize request; HTTP: POST initialize + store session)
    func initialize() async throws -> [String: Any]

    /// Call a tool by name with arguments, return result dict
    func callTool(name: String, arguments: [String: Any]) async throws -> [String: Any]

    /// Discover available tools (tools/list)
    func discoverTools() async throws -> [[String: Any]]

    /// Clean up connection (stdio: no-op or send shutdown; HTTP: DELETE session)
    func disconnect() async
}

/// Unified error type for both transports.
enum BridgeError: LocalizedError, Sendable {
    // Shared
    case notInitialized(String)          // bridge used before initialize()
    case serializationFailed(String)     // JSON encode/decode failure
    case timeout(String, TimeInterval)   // operation timed out

    // Stdio-specific
    case processNotRunning(String)       // child process exited
    case stdioPipeClosed(String)         // stdin/stdout pipe broken

    // HTTP-specific
    case httpError(String, Int, String)  // (mcpName, statusCode, message)
    case sessionExpired(String)          // 404 — session gone, needs re-init
    case connectionFailed(String, String) // (mcpName, underlying error description)

    // Transient vs permanent classification for retry logic
    var isTransient: Bool {
        switch self {
        case .timeout, .sessionExpired, .connectionFailed:
            return true
        case .httpError(_, let status, _):
            return status == 408 || status == 429 || (500...599).contains(status)
        default:
            return false
        }
    }

    var errorDescription: String? {
        switch self {
        case .notInitialized(let msg):
            return L10n.format("error.bridge.notInitialized", msg)
        case .serializationFailed(let msg):
            return L10n.format("error.bridge.serializationFailed", msg)
        case .timeout(let name, let duration):
            return L10n.format("error.bridge.timeout", name, String(format: "%.1f", duration))
        case .processNotRunning(let name):
            return L10n.format("error.bridge.processNotRunning", name)
        case .stdioPipeClosed(let name):
            return L10n.format("error.bridge.stdioPipeClosed", name)
        case .httpError(let name, let status, let msg):
            return L10n.format("error.bridge.httpError", name, Int64(status), msg)
        case .sessionExpired(let name):
            return L10n.format("error.bridge.sessionExpired", name)
        case .connectionFailed(let name, let error):
            return L10n.format("error.bridge.connectionFailed", name, error)
        }
    }
}
