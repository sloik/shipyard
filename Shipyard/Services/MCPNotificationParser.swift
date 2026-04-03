import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "MCPNotificationParser")

/// A type that can decode any JSON value and provide a string description
struct AnyCodable: Decodable, CustomStringConvertible, Sendable {
    let stringValue: String

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let str = try? container.decode(String.self) {
            stringValue = str
        } else if let dict = try? container.decode([String: String].self) {
            if let message = dict["message"] {
                stringValue = message
            } else {
                stringValue = dict.map { "\($0.key): \($0.value)" }.joined(separator: ", ")
            }
        } else if let num = try? container.decode(Double.self) {
            stringValue = String(num)
        } else if let bool = try? container.decode(Bool.self) {
            stringValue = String(bool)
        } else {
            stringValue = "(unknown)"
        }
    }

    var description: String { stringValue }
}

/// Parses MCP protocol notifications/message from server stdout
@MainActor final class MCPNotificationParser {

    /// MCP notification JSON structure
    private struct MCPMessage: Decodable, Sendable {
        let jsonrpc: String?
        let method: String?
        let params: Params?

        struct Params: Decodable, Sendable {
            let level: String?
            let logger: String?
            let data: AnyCodable?
        }
    }

    /// Parses a line from stdout and returns a LogEntry if it's a notifications/message
    func parse(line: String) -> LogEntry? {
        guard let data = line.data(using: .utf8) else { return nil }

        do {
            let message = try JSONDecoder().decode(MCPMessage.self, from: data)

            // Only handle notifications/message
            guard message.method == "notifications/message" else { return nil }
            guard let params = message.params else { return nil }

            let level = mapLevel(params.level)
            let text = params.data?.description ?? "(empty notification)"
            let loggerPrefix = params.logger.map { "[\($0)] " } ?? ""

            return LogEntry(
                timestamp: Date(),
                message: "\(loggerPrefix)\(text)",
                level: level,
                source: .mcp
            )
        } catch {
            // Not valid JSON or not an MCP message — ignore silently
            return nil
        }
    }

    /// Maps MCP log levels to our LogLevel
    func mapLevel(_ mcpLevel: String?) -> LogLevel {
        switch mcpLevel?.lowercased() {
        case "emergency", "alert", "critical", "error":
            return .error
        case "warning", "notice":
            return .warning
        case "info":
            return .info
        case "debug":
            return .debug
        default:
            return .info
        }
    }
}
