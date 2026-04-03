import Foundation

/// Source origin of an MCP server registration
enum MCPSource: String, Codable, Sendable {
    case manifest    // auto-discovered from manifest.json
    case config      // loaded from mcps.json
    case synthetic   // Shipyard itself (SPEC-008)
}

/// Transport protocol used by an MCP server
enum MCPTransport: String, Codable, Sendable {
    case stdio
    case streamableHTTP = "streamable-http"
    case sse  // Legacy HTTP+SSE (separate GET for stream, POST for messages)
}
